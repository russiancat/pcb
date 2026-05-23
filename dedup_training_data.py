#!/usr/bin/env python3
"""
One-time cleanup: remove duplicate .kicad_pcb files from data/training/,
rebuild candidates.json and hashes.json without the duplicates.

A duplicate is defined as a file whose MD5 hash matches an already-seen file.
The first occurrence (highest routing_pct, then most stars) is kept.

Usage:
    python dedup_training_data.py             # dry run — shows what would change
    python dedup_training_data.py --apply     # actually delete + rebuild state
"""

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/training")
    parser.add_argument("--apply", action="store_true",
                        help="delete duplicates and rewrite state files")
    args = parser.parse_args()

    root            = Path(args.output)
    candidates_path = root / "candidates.json"
    hashes_path     = root / "hashes.json"

    candidates = json.loads(candidates_path.read_text())

    # Sort best-first so we keep the highest-quality copy when there's a clash
    candidates.sort(key=lambda c: (-c["routing_pct"], -c["stars"]))

    seen_hashes: dict = {}   # hash → pcb_file path of first (kept) copy
    keep   = []
    remove = []

    for entry in candidates:
        p = Path(entry["pcb_file"])
        if not p.exists():
            print(f"  MISSING  {p}")
            remove.append(entry)
            continue
        h = hashlib.md5(p.read_bytes()).hexdigest()
        if h in seen_hashes:
            remove.append((entry, seen_hashes[h]))
        else:
            seen_hashes[h] = entry["pcb_file"]
            keep.append(entry)

    print(f"Total candidates : {len(candidates)}")
    print(f"Unique boards    : {len(keep)}")
    print(f"Duplicates       : {len(remove)}")
    print()

    for item in remove:
        if isinstance(item, tuple):
            entry, original = item
            print(f"  DUP  {entry['pcb_file']}")
            print(f"       kept: {original}")
        else:
            print(f"  MISSING  {item['pcb_file']}")

    if not args.apply:
        print("\nDry run — pass --apply to delete duplicates and rewrite state.")
        return

    # Delete duplicate PCB files and their score files
    deleted = 0
    for item in remove:
        entry = item[0] if isinstance(item, tuple) else item
        pcb = Path(entry["pcb_file"])
        score = pcb.with_suffix(".score.json")
        for f in (pcb, score):
            if f.exists():
                f.unlink()
                deleted += 1
                print(f"  deleted {f}")

    # Clean up empty directories left behind
    for d in sorted(root.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()   # only succeeds if empty
                print(f"  rmdir  {d}")
            except OSError:
                pass

    # Rewrite state files
    keep.sort(key=lambda c: (-c["routing_pct"], -c["stars"]))
    candidates_path.write_text(json.dumps(keep, indent=2))
    hashes_path.write_text(json.dumps(sorted(seen_hashes.keys()), indent=2))

    print(f"\nDeleted {deleted} files.")
    print(f"candidates.json  → {len(keep)} entries")
    print(f"hashes.json      → {len(seen_hashes)} hashes")


if __name__ == "__main__":
    main()
