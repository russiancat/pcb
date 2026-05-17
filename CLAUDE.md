# PCB Auto-Router — Project Context for Claude

## What This Is

A Python proof-of-concept for a PCB auto-router targeting hobbyists, with a long-term goal of a web-based PCB design tool. Core differentiator: **auto-placement (GNN) + auto-routing (A*)** — no schematic capture, import netlists/KiCad files only. Free for hobbyists with board size restriction.

Target users: hobbyists in developing countries (India etc.) who use cheaper manufacturers. Do NOT put "India" or "developing countries" in preset names — use "basic equipment" / "modern equipment".

## How to Run

```bash
# Route a KiCad board
MPLBACKEND=Agg .venv/bin/python kicad_demo.py path/to/board.kicad_pcb

# Run full benchmark across all demo boards
.venv/bin/python benchmark.py

# Simple synthetic demo (5-net board)
MPLBACKEND=Agg .venv/bin/python demo.py
```

Output images go to `demo_result.png` (kicad_demo) or `results/<board>.png` (benchmark).

## File Structure

```
router/
  board.py          Grid class — 2D per-layer numpy array, EMPTY/OBSTACLE/net_id
  astar.py          A* pathfinding — 8-directional, via support, octile heuristic
  router.py         Router — MST ordering, trunk-and-branch, rip-and-retry, copper pour
  netlist.py        Data classes: Pad, Net, Component
  design_rules.py   DesignRules presets (HOME_ETCH → PROFESSIONAL)
  kicad_parser.py   Parses .kicad_pcb files — handles KiCad 7/8 and KiCad 10 formats
visualize.py        matplotlib — two-panel (F.Cu / B.Cu), legend below, pour areas
kicad_demo.py       Load + route + visualise a single board
benchmark.py        Route all demo boards, compare vs existing KiCad routing
demo.py             Synthetic 5-net demo board
results/            Per-board benchmark PNGs (gitignore heavy, but keep for reference)
kicad-demo/         KiCad installation demo boards (copied locally)
data/               Synthetic test boards
```

## Architecture

```
.kicad_pcb file
    → KiCadBoard.from_file()       (kicad_parser.py)
    → nets: List[Net], components: List[Component]
    → Grid(width, height, resolution)
        mark_edge_keepout(cells)   ← apply BEFORE mark_pad
        mark_pad(x, y, layer, net_id)
    → Router(grid, trace_nets, rules)
        route_all()
          GlobalRouter.plan_all()  ← tile-level congestion map
          GlobalRouter.build_cost_map() → float32[layer,row,col]
          A* detailed routing with cost_map (soft congestion penalty)
          rip-and-retry with halved penalty each round
        copper_pour(net_id, layer) ← BFS flood-fill for GND/power planes
    → visualize.plot_board()       ← two-panel F.Cu / B.Cu, save_path param
    → benchmark quality metrics + DRC
```

## Key Design Decisions

### Grid
- **Resolution = trace width**: 1 cell = 1 trace width. Changing preset changes both.
- **Cell values**: EMPTY=0, OBSTACLE=-1, net_id (>0) = occupied
- **Clearance**: checked at query time in `is_passable()` using numpy slice. Only rejects FOREIGN NET traces (>0 and ≠ net_id). OBSTACLE cells do NOT count as clearance violations — allows routing to pads near component edges.
- **Edge keepout**: `mark_edge_keepout(cells)` marks border as OBSTACLE. Call BEFORE `mark_pad()` — pad cells override obstacles so edge-adjacent pads remain reachable.

### A* Router
- **8-directional moves**: 4 orthogonal (cost 1.0) + 4 diagonal (cost √2)
- **Octile distance heuristic**
- **Via**: switch layer at same position, cost = `rules.via_cost`
- **Diagonal corner-cutting** is checked and prevented
- `astar()` — routes to explicit (col, row) target on any layer
- `astar_to_net()` — routes to nearest existing cell of net_id (for trunk-and-branch)

### Routing Strategy
- **MST pad ordering** (`_mst_pad_order`): start with closest pair of pads, Prim's algorithm to add each subsequent pad closest to the existing tree. Builds compact trunk-and-branch topology instead of winding paths.
- **Global routing** (`GlobalRouter`): tiles the board (default 5mm²), plans each net through the least-congested tile corridor. Returns a `cost_map[layer,row,col]` (float32) that A* uses as soft penalty. Nets ordered by max tile congestion of their planned path (least-congested first — they take direct paths, leaving contested corridors for constrained nets).
- **Rip-and-retry**: failed nets are cleared and retried up to `max_iterations` times; each retry halves the congestion penalty so the router is progressively more tolerant.
- **Steiner-style multi-pin**: first pair uses `astar()`, subsequent pads use `astar_to_net()` to connect to existing trace tree

### Power Nets / Copper Pour
- GND and GND-variant nets (AGND, DGND etc.) are excluded from trace routing
- After trace routing completes, `copper_pour()` BFS flood-fills all reachable empty cells
- `POUR_NET_NAMES = {'GND', 'AGND', 'DGND', 'PGND', 'GND_ANALOG', 'GND_DIGITAL'}`
- Pour masks stored in `router.pour_masks[net_id][layer]` (bool numpy array)

### Design Rules Presets
```python
HOME_ETCH        resolution=1.0mm  clearance=1.0mm  via_cost=25.0  (default for home etchers)
LOCAL_FAB_BASIC  resolution=0.5mm  clearance=0.5mm  via_cost=8.0
LOCAL_FAB_MODERN resolution=0.3mm  clearance=0.3mm  via_cost=5.0
HOBBYIST_ONLINE  resolution=0.25mm clearance=0.25mm via_cost=4.0   (JLCPCB/PCBWay)
PROFESSIONAL     resolution=0.127mm clearance=0.127mm via_cost=3.0
```
Via cost is per-preset because vias are genuinely expensive for home etching (hand-drilled) but nearly free at online fabs.

### KiCad Parser
- Handles both KiCad 7/8 (`(net 1 "VCC")` numeric IDs) and KiCad 10 (`(net "VCC")` name-only)
- KiCad 10 reference: `(property "Reference" "U1")` not `(fp_text reference "U1")`
- Tokenizer regex: `[^\s()]+` (not `\S+`) — otherwise closing parens get eaten
- Component body obstacles are NOT marked (pad clearance zones are sufficient; courtyard data needed for proper implementation)

## Benchmark Results (as of last run — with global routing)

| Board | Our Nets% | KiCad Nets% | Our Wire vs KiCad | Shorts | Quality |
|-------|-----------|-------------|-------------------|--------|---------|
| multichannel_mixer | 98.8% | 98.8% | −7.0% shorter ✓ | 0 ✓ | 75.9 |
| complex_hierarchy | 96.2% | 94.2% | −22.6% shorter ✓ | 0 ✓ | 76.9 |
| ecc83-pp | 69.2% | 61.5% | −23.5% shorter ✓ | 0 ✓ | 55.4 |
| pic_programmer | 30.6% | 0% (unrouted) | n/a | 0 ✓ | — |
| interf_u | 58.5% | 63.6% | −8.2% shorter ✓ | 0 ✓ | 47.2 |
| CM5_MINIMA | 21.4% | 43.6% | −14.6% shorter | 0 ✓ | 17.1 |
| tinytapeout | 62.3% | 94.7% | −18.8% shorter | 0 ✓ | 49.8 |

Global routing improvements over previous pass: tinytapeout +10pp (52→62%), CM5 +3pp (18→21%).

Key observations:
- **Zero short circuits on every board** — routing is electrically clean.
- On nets we complete, **our wire is consistently shorter** than human/FreeRouting.
- CM5 and tinytapeout use far fewer vias than KiCad (0.21× and 0.24×) — KiCad switches layers aggressively; our via_cost=8 discourages this. Dense boards need lower via cost.
- CM5: 96 hot tiles (max_cong=20, cap=5) — physically too dense at 0.5mm resolution. Needs finer grid (HOBBYIST_ONLINE) or layer-aware zone planning.

## DRC Checks Implemented

| Check | Type | Status |
|-------|------|--------|
| Open nets (unrouted) | Hard | ✓ implemented |
| Board edge clearance | Hard | ✓ implemented (grid obstacle) |
| Short circuits (adjacent nets) | Hard | ✓ detected post-route |
| Trace-to-trace clearance | Hard | ✓ enforced during routing |

## Known Issues / Next Steps

### Routing quality improvements (ordered by impact)
1. **Lower via cost for dense boards** — CM5/tinytapeout use 0.2× reference via count. KiCad switches layers freely; our via_cost=8 prevents that. Try via_cost=3-4 for HOBBYIST_ONLINE or pass via_cost as a tunable parameter.
2. **Power net trunk / spine routing** — vbias routes 498% longer than reference. Needs a dedicated "route a spine trace across the board, then branch to each pad" strategy before the general A* pass.
3. **Layer-aware global routing** — current GlobalRouter doesn't distinguish layers. Assigning nets to preferred layers (F.Cu vs B.Cu) in the global pass would reduce layer-switch overhead and free up more space.
4. **Negotiated congestion (PathFinder)** — allow temporary overlaps during routing, then resolve conflicts iteratively with cost inflation. Proven to route boards that greedy A* cannot.

### Architecture / ML
6. **GNN for net ordering + strategy selection** — input: netlist graph + placement, output: strategy tag per net + routing order
7. **GNN for auto-placement** — predict component positions from netlist graph. Training data: KiCad boards with coordinates.
8. **RL training loop** — benchmark score becomes reward function: `Q = completion × wire_efficiency × via_efficiency`
9. **Zone decomposition** — GNN predicts coarse tile assignment, A* does detailed routing within constraints

### Product
10. **Web frontend** — backend: auth + storage (S3, no DB). All routing in browser.
11. **Board size restriction** for free tier
12. **Copper fills UI** — pour is implemented in router, needs UI exposure
13. **Export** — generate Gerber files from routed grid

## What NOT to Do
- Don't mark component body obstacles — they wall in pads. Use courtyard data when available.
- Don't use `\S+` in the tokenizer regex — it eats closing parentheses.
- Don't route GND/power nets as traces on dense boards — use copper pour.
- Don't mention "India" or "developing countries" in preset names.
- Don't call `mark_edge_keepout` after `mark_pad` — pads near edges will be lost.
- Don't set via_cost the same for all presets — home etch needs high cost, online fab needs low.

## Training Data for GNN
Every `.kicad_pcb` file with components placed on the board is a training example:
- Input: netlist graph (components as nodes, nets as edges with pad counts)
- Output: component x/y positions (for placement GNN)
- Output: net routing order + wire paths (for routing policy GNN)

Need ~500–1000 boards. Sources: KiCad GitHub repos, OSHPark public designs, KiCad demo library.
