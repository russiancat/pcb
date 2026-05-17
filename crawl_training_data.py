#!/usr/bin/env python3
"""
Crawl GitHub for KiCad PCB files and score them for GNN training-data quality.

Repos are discovered via topic search and GitHub code search, then each
.kicad_pcb file is downloaded, parsed, and scored against quality thresholds.
State is persisted so the script is safe to interrupt and resume.

Directory layout after a run:
    data/training/
      visited.json          {repo_full_name: {visited_at, files_dl, files_passed}}
      candidates.json       [{repo, file, metrics...}] — boards that pass thresholds
      owner__repo/
        board_name.kicad_pcb
        board_name.score.json

Usage:
    export GITHUB_TOKEN=ghp_...            # strongly recommended (10x more quota)
    python crawl_training_data.py
    python crawl_training_data.py --dry-run
    python crawl_training_data.py --max-repos 50
    python crawl_training_data.py --output data/training

Extra dependency (not needed for the router itself):
    pip install requests
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import requests
except ImportError:
    sys.exit("Missing dependency:  pip install requests")

from router.kicad_parser import KiCadBoard, _find_all, parse_sexp

# ── Search topics ─────────────────────────────────────────────────────────────

SEARCH_TOPICS = ["kicad", "kicad-pcb", "open-hardware", "pcb-design"]

# ── Quality thresholds ────────────────────────────────────────────────────────

MIN_NETS          = 5      # ignore trivial or symbol-only boards
MIN_ROUTING_PCT   = 75.0   # existing segments must cover ≥75% of nets
MIN_BOARD_MM      = 10.0   # filter out sub-centimetre test fixtures
MAX_BOARD_MM      = 500.0  # filter out panel / array boards
MAX_UNPLACED_PCT  = 20.0   # max % of components allowed outside board boundary

# ── Rate-limiting ─────────────────────────────────────────────────────────────

SEARCH_SLEEP  = 2.5   # seconds between search API calls
API_SLEEP     = 1.2   # seconds between other API calls
BACKOFF_SLEEP = 65.0  # seconds to wait on 403 / 429

API_BASE = "https://api.github.com"


# ── GitHub client ─────────────────────────────────────────────────────────────

class GitHubClient:
    """Thin wrapper around the GitHub REST API with rate-limit handling."""

    def __init__(self, token: Optional[str] = None):
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "pcb-training-data-crawler",
        })
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
        else:
            print("WARNING: no GITHUB_TOKEN — rate limited to 10 search req/min.",
                  file=sys.stderr)

    def _get(self, url: str, params: Optional[dict] = None,
             sleep: float = API_SLEEP) -> dict:
        time.sleep(sleep)
        for _ in range(4):
            try:
                resp = self._session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                print(f"  network error: {exc}", file=sys.stderr)
                time.sleep(API_SLEEP * 2)
                continue

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (403, 429):
                reset = int(resp.headers.get("X-RateLimit-Reset", 0))
                wait  = max(BACKOFF_SLEEP, reset - int(time.time()) + 5)
                print(f"  rate limited — sleeping {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                continue

            # 404=not found, 409=empty repo, 422=unprocessable, 451=DMCA
            if resp.status_code in (404, 409, 422, 451):
                return {}

            print(f"  HTTP {resp.status_code} — {url}", file=sys.stderr)
            return {}

        return {}

    def iter_repos_by_topic(self, topic: str):
        """Yield repos one page at a time for a topic tag (up to 10 pages)."""
        for page in range(1, 11):
            data  = self._get(
                f"{API_BASE}/search/repositories",
                params={"q": f"topic:{topic}", "per_page": 100, "page": page},
                sleep=SEARCH_SLEEP,
            )
            batch = data.get("items", [])
            yield from batch
            if len(batch) < 100:
                break

    def iter_repos_by_extension(self):
        """Yield repos one page at a time from kicad_pcb code search."""
        seen: set = set()
        for page in range(1, 11):
            data  = self._get(
                f"{API_BASE}/search/code",
                params={"q": "extension:kicad_pcb", "per_page": 100, "page": page},
                sleep=SEARCH_SLEEP,
            )
            batch = data.get("items", [])
            if not batch:
                break
            for item in batch:
                r = item.get("repository")
                if r and r["full_name"] not in seen:
                    seen.add(r["full_name"])
                    yield r
            if len(batch) < 100:
                break

    def get_tree(self, owner: str, repo: str, branch: str) -> List[dict]:
        """Return the full recursive file tree for a branch."""
        data = self._get(
            f"{API_BASE}/repos/{owner}/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        return data.get("tree", [])

    def default_branch(self, owner: str, repo: str) -> str:
        data = self._get(f"{API_BASE}/repos/{owner}/{repo}")
        return data.get("default_branch") or "main"

    def download_raw(self, owner: str, repo: str,
                     branch: str, path: str) -> Optional[bytes]:
        url = (f"https://raw.githubusercontent.com/"
               f"{owner}/{repo}/{branch}/{path}")
        time.sleep(API_SLEEP)
        try:
            resp = self._session.get(url, timeout=60)
            return resp.content if resp.status_code == 200 else None
        except requests.RequestException:
            return None


# ── Board scoring ─────────────────────────────────────────────────────────────

def _count_existing_routing(path: str, net_id_to_name: dict) -> Tuple[int, int]:
    """
    Return (routed_net_count, via_count) from segments already in the file.
    Measures human/tool routing quality — we do NOT run our own router here.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        tree = parse_sexp(fh.read())

    net_ids_with_wire: set = set()
    via_count = 0

    for seg in _find_all(tree, "segment"):
        for child in seg:
            if isinstance(child, list) and child and child[0] == "net":
                try:
                    net_ids_with_wire.add(int(float(child[1])))
                except (IndexError, ValueError):
                    pass

    for _ in _find_all(tree, "via"):
        via_count += 1

    routed_names = {
        net_id_to_name.get(nid, f"__net_{nid}") for nid in net_ids_with_wire
    }
    return len(routed_names), via_count


def score_board(path: Path) -> dict:
    """
    Parse and score a .kicad_pcb file for training-data quality.

    Returns a dict with all metrics and a boolean 'passes' field.
    Scoring is based on the EXISTING routing in the file (human/tool quality),
    not our A* router.
    """
    result: dict = {
        "file":                str(path),
        "passes":              False,
        "reason":              "",
        "net_count":           0,
        "component_count":     0,
        "board_w_mm":          0.0,
        "board_h_mm":          0.0,
        "routed_nets":         0,
        "routing_pct":         0.0,
        "via_count":           0,
        "off_board_components": 0,
    }

    try:
        board = KiCadBoard.from_file(str(path))
        nets, components = board.build_nets_and_components()
    except Exception as exc:
        result["reason"] = f"parse error: {exc}"
        return result

    net_count  = len(nets)
    comp_count = len(components)
    result["net_count"]       = net_count
    result["component_count"] = comp_count
    result["board_w_mm"]      = round(board.board_width,  2)
    result["board_h_mm"]      = round(board.board_height, 2)

    if net_count < MIN_NETS:
        result["reason"] = f"too few nets ({net_count})"
        return result

    w, h = board.board_width, board.board_height
    if w < MIN_BOARD_MM or h < MIN_BOARD_MM:
        result["reason"] = f"board too small ({w:.1f}×{h:.1f} mm)"
        return result
    if w > MAX_BOARD_MM or h > MAX_BOARD_MM:
        result["reason"] = f"board too large ({w:.1f}×{h:.1f} mm)"
        return result

    off_board = sum(
        1 for c in components
        if c.x < 0 or c.y < 0 or c.x > w or c.y > h
    )
    result["off_board_components"] = off_board
    if comp_count > 0 and 100.0 * off_board / comp_count > MAX_UNPLACED_PCT:
        result["reason"] = (f"too many off-board components "
                            f"({off_board}/{comp_count})")
        return result

    routed_nets, via_count = _count_existing_routing(str(path), board.nets)
    routing_pct = 100.0 * routed_nets / net_count if net_count else 0.0

    result["routed_nets"] = routed_nets
    result["routing_pct"] = round(routing_pct, 1)
    result["via_count"]   = via_count

    if routing_pct < MIN_ROUTING_PCT:
        result["reason"] = f"routing incomplete ({routing_pct:.1f}%)"
        return result

    result["passes"] = True
    result["reason"] = "ok"
    return result


# ── Per-repo processing ───────────────────────────────────────────────────────

def process_repo(
    client:     GitHubClient,
    repo:       dict,
    output_dir: Path,
    dry_run:    bool,
) -> Tuple[int, int]:
    """
    Download and score every .kicad_pcb file in repo.
    Returns (files_downloaded, files_passed).
    """
    owner     = repo["owner"]["login"]
    name      = repo["name"]
    branch    = repo.get("default_branch") or client.default_branch(owner, name)

    tree = client.get_tree(owner, name, branch)
    pcb_paths = [
        f["path"] for f in tree
        if f.get("type") == "blob" and f.get("path", "").endswith(".kicad_pcb")
    ]

    if not pcb_paths:
        print("  no .kicad_pcb files")
        return 0, 0

    print(f"  {len(pcb_paths)} .kicad_pcb file(s)  (branch: {branch})")

    repo_dir   = output_dir / repo["full_name"].replace("/", "__")
    downloaded = 0
    passed     = 0

    for file_path in pcb_paths:
        file_name = Path(file_path).name

        if dry_run:
            print(f"    [dry-run] {file_path}")
            continue

        content = client.download_raw(owner, name, branch, file_path)
        if content is None:
            print(f"    skip (download failed): {file_name}")
            continue

        repo_dir.mkdir(parents=True, exist_ok=True)
        local_pcb = repo_dir / file_name
        local_pcb.write_bytes(content)
        downloaded += 1

        score      = score_board(local_pcb)
        score_file = repo_dir / file_name.replace(".kicad_pcb", ".score.json")
        score_file.write_text(json.dumps(score, indent=2))

        status = "✓" if score["passes"] else f"✗  {score['reason']}"
        print(f"    {file_name}: {score['net_count']} nets, "
              f"{score['routing_pct']:.0f}% routed — {status}")

        if score["passes"]:
            passed += 1

    return downloaded, passed


# ── Candidates index ──────────────────────────────────────────────────────────

def _collect_candidates(repo: dict, repo_dir: Path) -> List[dict]:
    """Build candidate entries for all passing boards in repo_dir."""
    entries: List[dict] = []
    for score_file in sorted(repo_dir.glob("*.score.json")):
        score = json.loads(score_file.read_text())
        if not score.get("passes"):
            continue
        entries.append({
            "repo":            repo["full_name"],
            "stars":           repo.get("stargazers_count", 0),
            "file":            str(score_file).replace(".score.json", ".kicad_pcb"),
            "net_count":       score["net_count"],
            "component_count": score["component_count"],
            "board_w_mm":      score["board_w_mm"],
            "board_h_mm":      score["board_h_mm"],
            "routing_pct":     score["routing_pct"],
            "via_count":       score["via_count"],
        })
    return entries


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl GitHub for KiCad PCB files for GNN training data."
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub personal access token (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--max-repos", type=int, default=0,
        help="cap number of unvisited repos processed per run (0 = unlimited)",
    )
    parser.add_argument(
        "--output", default="data/training",
        help="root directory for downloaded files (default: data/training)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="discover repos and list files without downloading anything",
    )
    args = parser.parse_args()

    output_dir      = Path(args.output)
    visited_path    = output_dir / "visited.json"
    candidates_path = output_dir / "candidates.json"

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    visited:    dict = (json.loads(visited_path.read_text())
                        if visited_path.exists() else {})
    candidates: list = (json.loads(candidates_path.read_text())
                        if candidates_path.exists() else [])

    client = GitHubClient(args.token)

    # ── Lazy repo stream: search one page, process immediately, stop at cap ───
    def _repo_stream():
        """Yield unvisited repos across all search sources, one page at a time."""
        seen: set = set()
        for topic in SEARCH_TOPICS:
            print(f"Searching topic:{topic} ...")
            for repo in client.iter_repos_by_topic(topic):
                fn = repo["full_name"]
                if fn not in seen and fn not in visited:
                    seen.add(fn)
                    yield repo
        print("Searching code: extension:kicad_pcb ...")
        for repo in client.iter_repos_by_extension():
            fn = repo["full_name"]
            if fn not in seen and fn not in visited:
                seen.add(fn)
                yield repo

    # ── Process repos ─────────────────────────────────────────────────────────
    total_dl     = 0
    total_passed = 0
    processed    = 0

    for repo in _repo_stream():
        if args.max_repos and processed >= args.max_repos:
            print(f"\nReached --max-repos {args.max_repos} — stopping.")
            break

        processed += 1
        full_name  = repo["full_name"]
        stars      = repo.get("stargazers_count", 0)
        print(f"\n[{processed}] {full_name}  ★{stars}")

        try:
            dl, passed = process_repo(client, repo, output_dir, args.dry_run)
            total_dl     += dl
            total_passed += passed

            if not args.dry_run:
                visited[full_name] = {
                    "visited_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "files_dl":     dl,
                    "files_passed": passed,
                }
                visited_path.write_text(json.dumps(visited, indent=2))

                if passed:
                    repo_dir    = output_dir / full_name.replace("/", "__")
                    new_entries = _collect_candidates(repo, repo_dir)
                    existing    = {c["file"] for c in candidates}
                    candidates.extend(e for e in new_entries
                                      if e["file"] not in existing)
                    candidates.sort(key=lambda c: (-c["routing_pct"], -c["stars"]))
                    candidates_path.write_text(json.dumps(candidates, indent=2))

        except KeyboardInterrupt:
            print("\nInterrupted — progress saved.")
            break
        except Exception as exc:
            print(f"  ERROR: {exc}")
            if not args.dry_run:
                visited[full_name] = {
                    "visited_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error":      str(exc),
                }
                visited_path.write_text(json.dumps(visited, indent=2))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"Downloaded : {total_dl} files")
    print(f"Passed     : {total_passed} files")
    print(f"Candidates : {len(candidates)} total  →  {candidates_path}")


if __name__ == "__main__":
    main()
