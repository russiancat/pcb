"""
Demo: route a small 2-layer board using A* + rip-and-retry.
"""

import time

from router.board import Grid
from router.manufacturer_profile import HOME_ETCH, JLCPCB_2L, PCBWAY_2L, ZBOTIC_2L
from router.netlist import Component, Net, Pad
from router.router import Router
from visualize import plot_board

# ------------------------------------------------------------------
# Pick your target manufacturer profile here
# ------------------------------------------------------------------
PROFILE = HOME_ETCH    # change to JLCPCB_2L, PCBWAY_2L, ZBOTIC_2L, etc.
RULES   = PROFILE.design_rules

BOARD_W = 40.0
BOARD_H = 30.0

print(RULES.summary())
print()

# ------------------------------------------------------------------
# Components
# ------------------------------------------------------------------
cc = RULES.component_clearance_mm   # keepout around body edges

components = [
    Component("J1",   x=0.5,  y=7.0,  width=3.0, height=16.5, pads=[
        Pad(1, 2.0, 22.0, layer=0),   # VCC
        Pad(2, 2.0,  8.0, layer=0),   # GND
    ]),
    Component("C1",   x=11.0, y=24.0, width=4.0, height=2.0, pads=[
        Pad(1, 12.0, 25.0, layer=0),  # +
        Pad(2, 14.0, 25.0, layer=0),  # -
    ]),
    Component("U1",   x=18.0, y=6.0,  width=6.0, height=18.0, pads=[
        Pad(1, 18.0, 24.0, layer=0),  # VCC  top-left
        Pad(2, 18.0,  6.0, layer=0),  # GND  bot-left
        Pad(3, 24.0, 24.0, layer=0),  # OUT  top-right
        Pad(4, 24.0,  6.0, layer=0),  # IN   bot-right
    ]),
    Component("R1",   x=29.0, y=21.0, width=4.0, height=2.0, pads=[
        Pad(3, 30.0, 22.0, layer=0),
        Pad(4, 32.0, 22.0, layer=0),
    ]),
    Component("LED1", x=34.5, y=12.0, width=3.0, height=6.0, pads=[
        Pad(4, 36.0, 17.0, layer=0),  # anode
        Pad(5, 36.0, 13.0, layer=0),  # cathode
    ]),
]

# ------------------------------------------------------------------
# Nets
# ------------------------------------------------------------------
nets = [
    Net(1, "VCC",  (Pad(1, 2.0, 22.0), Pad(1, 12.0, 25.0), Pad(1, 18.0, 24.0))),
    Net(2, "GND",  (Pad(2, 2.0,  8.0), Pad(2, 14.0, 25.0), Pad(2, 18.0,  6.0))),
    Net(3, "SIG1", (Pad(3, 24.0, 24.0), Pad(3, 30.0, 22.0))),
    Net(4, "SIG2", (Pad(4, 32.0, 22.0), Pad(4, 36.0, 17.0))),
    Net(5, "SIG3", (Pad(5, 24.0,  6.0), Pad(5, 36.0, 13.0))),
]

# ------------------------------------------------------------------
# Build grid
# ------------------------------------------------------------------
grid = Grid(BOARD_W, BOARD_H, resolution=RULES.resolution_mm)

for net in nets:
    for pad in net.pads:
        grid.mark_pad(pad.x, pad.y, pad.layer, net.net_id)

# Mark U1 body + component keepout as obstacle
# Shrink slightly so pad cells (on the body edge) stay accessible
grid.mark_obstacle_rect(
    18.0 + RULES.resolution_mm,
    6.0  + RULES.resolution_mm,
    6.0  - 2 * RULES.resolution_mm,
    18.0 - 2 * RULES.resolution_mm,
)

# ------------------------------------------------------------------
# Route
# ------------------------------------------------------------------
print(f"Grid: {grid.cols} x {grid.rows} cells  "
      f"({grid.cols * grid.rows * grid.num_layers:,} states)  "
      f"clearance: {RULES.clearance_cells} cell(s)")
print(f"Routing {len(nets)} nets ...\n")

router = Router(grid, nets, rules=RULES, max_iterations=3)
t0 = time.perf_counter()
failed = router.route_all()
elapsed = time.perf_counter() - t0

print(f"Time  : {elapsed:.3f}s")
if failed:
    print(f"Unrouted: {[n.name for n in failed]}")

# ------------------------------------------------------------------
# Visualize
# ------------------------------------------------------------------
plot_board(
    grid, nets, router, components,
    title=(f"A* Router — {BOARD_W}×{BOARD_H}mm  |  "
           f"{RULES.name}  |  "
           f"trace {RULES.resolution_mm}mm / clearance {RULES.clearance_mm}mm")
)
