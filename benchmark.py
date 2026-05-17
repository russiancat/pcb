"""
Benchmark our A* router against existing KiCad routing.

For each board:
  - Parse component placements + netlist from the KiCad file
  - Measure the EXISTING routing (segments/vias already in the file)
  - Run OUR A* router from scratch (placements only, no existing traces)
  - Print side-by-side comparison including quality metrics and basic DRC
"""

import math
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from router import POUR_NET_NAMES
from router.board import Grid
from router.design_rules import LOCAL_FAB_BASIC
from router.kicad_parser import KiCadBoard, parse_sexp, _find_all
from router.router import Router
from visualize import plot_board

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

RULES = LOCAL_FAB_BASIC
POUR_NAMES = POUR_NET_NAMES

BOARDS = [
    "kicad-demo/demos/multichannel/multichannel_mixer.kicad_pcb",
    "kicad-demo/demos/ecc83/ecc83-pp.kicad_pcb",
    "kicad-demo/demos/ecc83/ecc83-pp_v2.kicad_pcb",
    "kicad-demo/demos/complex_hierarchy/complex_hierarchy.kicad_pcb",
    "kicad-demo/demos/pic_programmer/pic_programmer.kicad_pcb",
    "kicad-demo/demos/interf_u/interf_u.kicad_pcb",
    "kicad-demo/demos/cm5_minima/CM5_MINIMA_3.kicad_pcb",
    "kicad-demo/demos/tiny_tapeout/tinytapeout-demo.kicad_pcb",
]


# ------------------------------------------------------------------
# Parse existing routing: per-net wire lengths + via count
# ------------------------------------------------------------------

def _coord(node, tag):
    for child in node:
        if isinstance(child, list) and child and child[0] == tag:
            return float(child[1]), float(child[2])
    return None, None


def _net_id_from_node(node):
    for child in node:
        if isinstance(child, list) and child and child[0] == "net":
            try:
                return int(float(child[1]))
            except (IndexError, ValueError):
                pass
    return None


def parse_existing_routing(path: str, kicad_id_to_name: dict):
    """
    Returns:
        via_count        : int
        wire_by_name     : dict[net_name -> float mm]   per-net wire length
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    tree = parse_sexp(text)

    wire_by_id: dict = {}   # kicad net id -> float mm
    via_count = 0

    for seg in _find_all(tree, "segment"):
        x1, y1 = _coord(seg, "start")
        x2, y2 = _coord(seg, "end")
        if x1 is None:
            continue
        length = math.hypot(x2 - x1, y2 - y1)
        nid = _net_id_from_node(seg)
        if nid is not None:
            wire_by_id[nid] = wire_by_id.get(nid, 0.0) + length

    for via in _find_all(tree, "via"):
        via_count += 1

    # Map kicad net IDs → net names using the board's net table
    wire_by_name: dict = {}
    for kid, wlen in wire_by_id.items():
        name = kicad_id_to_name.get(kid, f"__net_{kid}")
        wire_by_name[name] = wire_by_name.get(name, 0.0) + wlen

    return via_count, wire_by_name


# ------------------------------------------------------------------
# DRC checks (post-route, on the grid)
# ------------------------------------------------------------------

def run_drc(grid: Grid, nets: list, router: Router, rules) -> list:
    """
    DRC checks. Returns a list of violation strings categorised as:
      OPEN             — unrouted net
      EDGE_CLEARANCE   — trace within edge keepout zone
      SHORT_CIRCUIT    — two routed TRACES of different nets adjacent
                         (true routing bug; pad-to-pad adjacency is excluded)
      PAD_CLEARANCE    — pad of one net adjacent to pad/trace of another
                         (placement concern, not a routing bug)
    """
    import numpy as np
    violations = []

    routed_ids = set(router.routed.keys()) | set(router.pour_masks.keys())
    pour_ids   = set(router.pour_masks.keys())
    pad_cells  = grid._pad_cells  # set of (layer, row, col)

    # 1. Unrouted nets
    for net in nets:
        if net.net_id not in routed_ids:
            violations.append(f"OPEN: {net.name} ({len(net.pads)} pads unconnected)")

    # 2. Board edge clearance — traces inside the keepout border
    ec = max(1, round(rules.edge_clearance_mm / rules.resolution_mm))
    g = grid.grid
    rows, cols = grid.rows, grid.cols
    for layer in range(grid.num_layers):
        layer_grid = g[layer]
        for r in range(rows):
            for c in range(cols):
                cell = layer_grid[r, c]
                if cell <= 0 or cell in pour_ids:
                    continue
                if (layer, r, c) in pad_cells:
                    continue    # edge-adjacent pads are a placement issue, not routing
                near_edge = (r < ec or r >= rows - ec or
                             c < ec or c >= cols - ec)
                if near_edge:
                    x, y = grid.grid_to_mm(c, r)
                    violations.append(
                        f"EDGE_CLEARANCE: net {cell} trace at "
                        f"({x:.1f},{y:.1f})mm layer {layer}"
                    )

    # 3. Adjacent-cell conflicts — distinguish true shorts from pad clearance issues
    def _classify_adj(layer, r1, c1, r2, c2):
        net_a = g[layer, r1, c1]
        net_b = g[layer, r2, c2]
        if net_a <= 0 or net_b <= 0 or net_a == net_b:
            return
        x, y = grid.grid_to_mm(c1, r1)
        a_is_pad = (layer, r1, c1) in pad_cells
        b_is_pad = (layer, r2, c2) in pad_cells
        if a_is_pad or b_is_pad:
            violations.append(
                f"PAD_CLEARANCE: net {net_a} vs net {net_b} "
                f"at ({x:.1f},{y:.1f})mm layer {layer}"
            )
        else:
            violations.append(
                f"SHORT_CIRCUIT: net {net_a} vs net {net_b} "
                f"at ({x:.1f},{y:.1f})mm layer {layer}"
            )

    for layer in range(grid.num_layers):
        lg = g[layer]
        hor = np.where((lg[:, :-1] > 0) & (lg[:, 1:] > 0) & (lg[:, :-1] != lg[:, 1:]))
        for r, c in zip(hor[0], hor[1]):
            _classify_adj(layer, r, c, r, c + 1)
        ver = np.where((lg[:-1, :] > 0) & (lg[1:, :] > 0) & (lg[:-1, :] != lg[1:, :]))
        for r, c in zip(ver[0], ver[1]):
            _classify_adj(layer, r, c, r + 1, c)

    return violations


# ------------------------------------------------------------------
# Route a board with our A* router
# ------------------------------------------------------------------

def route_board(path: str):
    board = KiCadBoard.from_file(path)
    nets, components = board.build_nets_and_components()

    if not nets:
        return None

    off_board = sum(
        1 for c in components
        if c.x < 0 or c.y < 0
        or c.x > board.board_width or c.y > board.board_height
    )

    grid = Grid(board.board_width, board.board_height,
                resolution=RULES.resolution_mm)

    edge_cells = max(1, round(RULES.edge_clearance_mm / RULES.resolution_mm))
    grid.mark_edge_keepout(edge_cells)

    for net in nets:
        for pad in net.pads:
            grid.mark_pad(pad.x, pad.y, pad.layer, net.net_id)

    pour_nets  = [n for n in nets if n.name.upper() in POUR_NAMES]
    trace_nets = [n for n in nets if n.name.upper() not in POUR_NAMES]

    router = Router(grid, trace_nets, rules=RULES, max_iterations=3)
    t0 = time.perf_counter()
    failed = router.route_all()
    elapsed = time.perf_counter() - t0

    for pnet in pour_nets:
        for lyr in range(grid.num_layers):
            router.copper_pour(pnet.net_id, lyr)

    # Per-net wire lengths for quality comparison
    our_wire_by_name: dict = {}
    our_wire_mm = 0.0
    for net in trace_nets:
        paths = router.routed.get(net.net_id, [])
        w = 0.0
        for path in paths:
            prev = None
            for col, row, layer in path:
                if prev is not None:
                    pc, pr, _ = prev
                    w += math.hypot(col - pc, row - pr) * RULES.resolution_mm
                prev = (col, row, layer)
        if w > 0:
            our_wire_by_name[net.name] = w
            our_wire_mm += w

    our_vias    = sum(len(v) for v in router.vias.values())
    routed_count = len(router.routed) + len(router.pour_masks)

    # DRC
    drc_violations = run_drc(grid, nets, router, RULES)

    return {
        "_board":      board,
        "_objects":    (grid, nets, router, components),
        "board_w":     board.board_width,
        "board_h":     board.board_height,
        "total_nets":  len(nets),
        "parts":       len(components),
        "off_board":   off_board,
        "our_routed":  routed_count,
        "our_pct":     100.0 * routed_count / len(nets) if nets else 0,
        "our_wire_mm": our_wire_mm,
        "our_wire_by_name": our_wire_by_name,
        "our_vias":    our_vias,
        "our_time_s":  elapsed,
        "failed":      [n.name for n in failed],
        "drc":         drc_violations,
    }


# ------------------------------------------------------------------
# Quality score: compare wire lengths on nets both routers completed
# ------------------------------------------------------------------

def quality_report(res: dict, ref_wire_by_name: dict, ref_vias: int) -> dict:
    our  = res["our_wire_by_name"]
    common = set(our.keys()) & set(ref_wire_by_name.keys())

    if not common:
        return {}

    ref_common  = sum(ref_wire_by_name[n] for n in common)
    our_common  = sum(our[n] for n in common)
    wire_overhead_pct = (our_common - ref_common) / ref_common * 100 if ref_common else 0

    # Nets where we route significantly longer (>50% over reference)
    worse_nets = sorted(
        [(n, our[n], ref_wire_by_name[n],
          100*(our[n]-ref_wire_by_name[n])/ref_wire_by_name[n])
         for n in common if our[n] > ref_wire_by_name[n] * 1.5],
        key=lambda x: -x[3]
    )

    # Nets where we're actually shorter (bonus)
    better_nets = [n for n in common if our[n] < ref_wire_by_name[n] * 0.9]

    via_ratio = res["our_vias"] / ref_vias if ref_vias else None

    # Simple quality index: 0–100
    # completion × wire_efficiency × via_efficiency (each clamped 0–1)
    comp_score = res["our_pct"] / 100.0
    wire_score = min(1.0, ref_common / our_common) if our_common else 0
    via_score  = min(1.0, ref_vias / res["our_vias"]) if res["our_vias"] and ref_vias else 1.0
    quality_index = round(100 * comp_score * (0.5*wire_score + 0.3) * (0.2*via_score + 0.8), 1)

    return {
        "matched_nets":      len(common),
        "wire_overhead_pct": wire_overhead_pct,
        "worse_nets":        worse_nets[:5],
        "better_nets_count": len(better_nets),
        "via_ratio":         via_ratio,
        "quality_index":     quality_index,
    }


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    W = 50
    SEP = "=" * 130

    for path in BOARDS:
        name = Path(path).stem
        print(f"\n{SEP}")
        print(f"  {name}")
        print(SEP)

        try:
            # Route with our A*
            res = route_board(path)
            if res is None:
                print("  No nets — skipped.")
                continue

            # Parse existing routing for comparison
            board      = res["_board"]
            kid_to_name = board.nets          # kicad net_id -> name
            ref_vias, ref_wire_by_name = parse_existing_routing(path, kid_to_name)
            ref_wire_total = sum(ref_wire_by_name.values())

        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  ERROR: {e}")
            continue

        # ── Summary ───────────────────────────────────────────────
        size_str = f"{res['board_w']:.0f}×{res['board_h']:.0f} mm"
        off_note = f"  ({res['off_board']} parts off-board)" if res["off_board"] else ""
        print(f"  Size    : {size_str}{off_note}")
        print(f"  Nets    : {res['total_nets']}   Parts: {res['parts']}")
        print()

        ex_pct = 100.0 * len(ref_wire_by_name) / res["total_nets"] if res["total_nets"] else 0
        print(f"  {'':25s}  {'KiCad reference':>22s}    {'Our A* router':>22s}")
        print(f"  {'Net completion':25s}  {ex_pct:>21.1f}%    {res['our_pct']:>21.1f}%")
        print(f"  {'Total wire length':25s}  {ref_wire_total/1000:>20.2f}m    {res['our_wire_mm']/1000:>20.2f}m")
        print(f"  {'Via count':25s}  {ref_vias:>22d}    {res['our_vias']:>22d}")
        print(f"  {'Routing time':25s}  {'(hand/FreeRouting)':>22s}    {res['our_time_s']:>20.1f}s")

        # ── Quality score ─────────────────────────────────────────
        qr = quality_report(res, ref_wire_by_name, ref_vias)
        if qr:
            print()
            print(f"  ── Quality (on {qr['matched_nets']} nets both routers completed) ──")
            print(f"  Wire overhead vs reference : {qr['wire_overhead_pct']:+.1f}%  "
                  f"({'shorter' if qr['wire_overhead_pct'] < 0 else 'longer'} than KiCad)")
            print(f"  Nets we route shorter      : {qr['better_nets_count']}")
            via_str = f"{qr['via_ratio']:.2f}× reference" if qr["via_ratio"] else "n/a"
            print(f"  Via usage vs reference     : {via_str}")
            print(f"  Quality index (0–100)      : {qr['quality_index']}")
            if qr["worse_nets"]:
                print(f"  Worst nets (our wire >> ref):")
                for nm, ow, rw, pct in qr["worse_nets"]:
                    print(f"    {nm:35s}  ours={ow:.1f}mm  ref={rw:.1f}mm  (+{pct:.0f}%)")

        # ── DRC ───────────────────────────────────────────────────
        drc = res["drc"]
        opens   = [v for v in drc if v.startswith("OPEN")]
        edges   = [v for v in drc if v.startswith("EDGE")]
        shorts  = [v for v in drc if v.startswith("SHORT_CIRCUIT")]
        padclr  = [v for v in drc if v.startswith("PAD_CLEARANCE")]
        print()
        print(f"  ── DRC ──")
        print(f"  Open nets           : {len(opens)}")
        print(f"  Edge clearance viol : {len(edges)}"
              + (f"  e.g. {edges[0][:70]}" if edges else ""))
        print(f"  Short circuits      : {len(shorts)}"
              + (f"  *** {shorts[0]}" if shorts else " ✓  (routing is clean)"))
        pad_note = "  (placement issue, not routing)" if padclr else ""
        print(f"  Pad clearance viol  : {len(padclr)}{pad_note}")

        if res["failed"]:
            print(f"  Unrouted nets: {', '.join(res['failed'][:8])}"
                  + (" ..." if len(res["failed"]) > 8 else ""))

        # ── Save image ────────────────────────────────────────────
        try:
            grid, nets_obj, router_obj, comps_obj = res["_objects"]
            img_path = str(RESULTS_DIR / f"{name}.png")
            subtitle = (
                f"{name}  |  {RULES.name}  |  "
                f"Our: {res['our_routed']}/{res['total_nets']} nets  "
                f"{res['our_vias']} vias  {res['our_wire_mm']/1000:.2f}m"
                + (f"  wire+{qr['wire_overhead_pct']:+.0f}%  Q={qr['quality_index']}" if qr else "")
                + f"  ||  KiCad ref: {ref_vias} vias  {ref_wire_total/1000:.2f}m"
            )
            plot_board(grid, nets_obj, router_obj, comps_obj,
                       title=subtitle, save_path=img_path)
            plt.close("all")
            print(f"  Saved {img_path}")
        except Exception as e:
            print(f"  (image save failed: {e})")

    print(f"\n{SEP}")


if __name__ == "__main__":
    main()
