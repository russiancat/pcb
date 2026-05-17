"""
Load a .kicad_pcb file, auto-route it, and visualise the result.

Usage:
    python kicad_demo.py                          # uses default test board
    python kicad_demo.py path/to/your.kicad_pcb  # your own file
"""

import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="  %(message)s")

from router import POUR_NET_NAMES
from router.board import Grid
from router.kicad_parser import KiCadBoard
from router.manufacturer_profile import HOME_ETCH, JLCPCB_2L, PCBWAY_2L
from router.router import Router
from visualize import plot_board

# ------------------------------------------------------------------
# Config — pick a manufacturer profile
# ------------------------------------------------------------------
PCB_FILE = sys.argv[1] if len(sys.argv) > 1 else "data/test_board.kicad_pcb"
PROFILE  = JLCPCB_2L        # change to PCBWAY_2L, HOME_ETCH, etc.
RULES    = PROFILE.design_rules

# ------------------------------------------------------------------
# Parse
# ------------------------------------------------------------------
print(f"Loading: {PCB_FILE}")
board = KiCadBoard.from_file(PCB_FILE)
nets, components = board.build_nets_and_components()

print(f"Board   : {board.board_width:.1f} x {board.board_height:.1f} mm")
print(f"Nets    : {len(nets)}")
print(f"Parts   : {len(components)}")
print(f"Rules   : {RULES.name}")
print()

# ------------------------------------------------------------------
# Build grid
# ------------------------------------------------------------------
grid = Grid(board.board_width, board.board_height, resolution=RULES.resolution_mm)

# Edge keepout: mark border cells as obstacles before placing pads.
# Pad cells override the obstacle so edge-adjacent pads remain reachable,
# but no trace is allowed to run along the board boundary.
edge_cells = max(1, round(RULES.edge_clearance_mm / RULES.resolution_mm))
grid.mark_edge_keepout(edge_cells)

# Mark pads. Component body obstacles are intentionally skipped here:
# - THT components (DIP, connectors) sit above the board; traces route under them.
# - SMD component bodies are small; their pads' clearance zones already prevent
#   other nets from routing too close.
# Body obstacles will be added back once we have courtyard data from the KiCad file.
for net in nets:
    for pad in net.pads:
        grid.mark_pad(pad.x, pad.y, pad.layer, net.net_id)

print(f"Grid    : {grid.cols} x {grid.rows} cells  "
      f"({grid.cols * grid.rows * grid.num_layers:,} states)  "
      f"clearance: {RULES.clearance_cells} cell(s)")

pour_nets = [n for n in nets if n.name.upper() in POUR_NET_NAMES]
trace_nets = [n for n in nets if n.name.upper() not in POUR_NET_NAMES]
if pour_nets:
    print(f"Pour    : {', '.join(n.name for n in pour_nets)} (copper pour, not traced)")
print(f"Routing {len(trace_nets)} trace nets ...\n")

# ------------------------------------------------------------------
# Route
# ------------------------------------------------------------------
router = Router(grid, trace_nets, rules=RULES, max_iterations=3)
t0 = time.perf_counter()
failed = router.route_all()
elapsed = time.perf_counter() - t0

print(f"\nTime    : {elapsed:.3f}s")
print(f"Vias    : {sum(len(v) for v in router.vias.values())}")
if failed:
    print(f"UNROUTED: {[n.name for n in failed]}")

# ------------------------------------------------------------------
# Copper pour (flood-fill GND / power planes)
# ------------------------------------------------------------------
if pour_nets:
    print("\nCopper pour ...")
    for pnet in pour_nets:
        for lyr in range(grid.num_layers):
            filled = router.copper_pour(pnet.net_id, lyr)
            if filled:
                print(f"  {pnet.name} layer {lyr}: {filled} cells poured")

# ------------------------------------------------------------------
# Visualise
# ------------------------------------------------------------------
plot_board(
    grid, nets, router, components,
    title=(f"{PCB_FILE}  |  {RULES.name}  |  "
           f"trace {RULES.resolution_mm}mm / clearance {RULES.clearance_mm}mm")
)
