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
  global_router.py  GlobalRouter — tile-level congestion planning, cost_map
  netlist.py        Data classes: Pad, Net, Component
  design_rules.py   DesignRules dataclass only — no presets
  drc.py            ViolationType enum, DRCViolation dataclass, run_drc()
  quality.py        QualityReport dataclass, quality_report()
  kicad_parser.py   Parses .kicad_pcb files — handles KiCad 7/8 and KiCad 10 formats
  kicad_writer.py   KiCadWriter — appends routed segments/vias to a .kicad_pcb file
  __init__.py       POUR_NET_NAMES frozenset
visualize.py        matplotlib — two-panel (F.Cu / B.Cu), legend below, pour areas
kicad_demo.py       Load + route + visualise a single board
benchmark.py        Route all demo boards, compare vs existing KiCad routing
demo.py             Synthetic 5-net demo board
crawl_training_data.py  Crawl GitHub for KiCad files → score → build GNN training set
tests/              pytest test suite (46 tests)
results/            Per-board benchmark PNGs (gitignore heavy, but keep for reference)
kicad-demo/         KiCad installation demo boards (copied locally)
data/               Synthetic test boards
data/training/      GNN training data (downloaded by crawl_training_data.py)
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
- **MST pad ordering** (`Router._mst_pad_order`): start with closest pair of pads, Prim's algorithm to add each subsequent pad closest to the existing tree. Builds compact trunk-and-branch topology instead of winding paths.
- **Global routing** (`GlobalRouter`): tiles the board (default 5mm²), plans each net through the least-congested tile corridor. Returns a `cost_map[layer,row,col]` (float32) that A* uses as soft penalty. Nets ordered by max tile congestion of their planned path (least-congested first — they take direct paths, leaving contested corridors for constrained nets).
- **Rip-and-retry**: failed nets are cleared and retried up to `max_iterations` times; each retry halves the congestion penalty so the router is progressively more tolerant.
- **Steiner-style multi-pin**: first pair uses `astar()`, subsequent pads use `astar_to_net()` to connect to existing trace tree

### Power Nets / Copper Pour
- GND and GND-variant nets (AGND, DGND etc.) are excluded from trace routing
- After trace routing completes, `copper_pour()` BFS flood-fills all reachable empty cells
- `POUR_NET_NAMES = {'GND', 'AGND', 'DGND', 'PGND', 'GND_ANALOG', 'GND_DIGITAL'}`
- Pour masks stored in `router.pour_masks[net_id][layer]` (bool numpy array)

### Manufacturer Profiles
Loaded from `router/profiles/*.toml` at import time (Python 3.11+ `tomllib`, zero extra deps).
Named constants in `router/manufacturer_profile.py`:
```
HOME_ETCH    resolution=1.0mm  clearance=1.0mm  via_cost=25.0  (home etching)
PCBWAY_2L    resolution=0.127mm clearance=0.127mm via_cost=4.0  (PCBWay 2-layer)
PCBWAY_4L    resolution=0.1mm  clearance=0.1mm  via_cost=3.0   (PCBWay 4-layer)
JLCPCB_2L   resolution=0.127mm clearance=0.127mm via_cost=4.0  (JLCPCB 2-layer)
JLCPCB_4L   resolution=0.1mm  clearance=0.1mm  via_cost=3.0   (JLCPCB 4-layer)
ZBOTIC_2L   resolution=0.15mm clearance=0.15mm  via_cost=4.0  (ZBOTIC 2-layer)
ZBOTIC_4L   resolution=0.1mm  clearance=0.1mm  via_cost=3.0   (ZBOTIC 4-layer)
```
Via cost is per-profile: hand-drilled vias (home etch) are expensive; machine-drilled vias at online fabs are nearly free.
Add a new manufacturer by adding a `.toml` file to `router/profiles/` — no Python code needed.
Use `ManufacturerProfile.merge(a, b)` for strictest-wins constraint merging.

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
- CM5: 96 hot tiles (max_cong=20, cap=5) — physically too dense at 0.5mm resolution. Needs finer grid (JLCPCB_2L/PCBWAY_2L at 0.127mm) or layer-aware zone planning.

## DRC Checks Implemented

Violations live in `router/drc.py` as typed `DRCViolation(type: ViolationType, description: str)`.
Filter by `v.type == ViolationType.SHORT_CIRCUIT` — never string-match on `str(v)`.

| Check | ViolationType | Status |
|-------|--------------|--------|
| Open nets (unrouted) | OPEN | ✓ implemented |
| Board edge clearance | EDGE_CLEARANCE | ✓ implemented (grid obstacle) |
| Short circuits (adjacent nets) | SHORT_CIRCUIT | ✓ detected post-route |
| Pad-to-pad/trace adjacency | PAD_CLEARANCE | ✓ detected (placement issue, not routing) |
| Trace-to-trace clearance | — | ✓ enforced during routing (A* is_passable) |

## Known Issues / Next Steps

### Routing quality improvements (ordered by impact)
1. **Lower via cost for dense boards** — CM5/tinytapeout use 0.2× reference via count. KiCad switches layers freely; our via_cost=8 prevents that. Try via_cost=3-4 (JLCPCB_4L/PCBWAY_4L profiles) or pass via_cost as a tunable parameter.
2. **Power net trunk / spine routing** — vbias routes 498% longer than reference. Needs a dedicated "route a spine trace across the board, then branch to each pad" strategy before the general A* pass.
3. **Layer-aware global routing** — current GlobalRouter doesn't distinguish layers. Assigning nets to preferred layers (F.Cu vs B.Cu) in the global pass would reduce layer-switch overhead and free up more space.
4. **Negotiated congestion (PathFinder)** — allow temporary overlaps during routing, then resolve conflicts iteratively with cost inflation. Proven to route boards that greedy A* cannot.

### Code architecture (known debt)
5. **`KiCadBoard` two-phase construction** (`kicad_parser.py`) — `_name_to_id` and `_next_id` are parse-time state leaked as dataclass fields. Violates "constructors build complete objects." Fix: move parse state into a `_Parser` inner class that returns an immutable `KiCadBoard`.
6. **A* code duplication** — `_astar` and `_astar_to_net` in `astar.py` share ~70% of the same loop body. `GlobalRouter._tile_astar` re-implements A* a third time. Consolidate behind a shared `_run_astar(stop_condition)` closure to eliminate the duplication.

### Architecture / ML
7. **Training data collection (in progress)** — `crawl_training_data.py` crawls GitHub topics (`kicad`, `kicad-pcb`, `open-hardware`, `pcb-design`) and code search (`extension:kicad_pcb`). Quality thresholds: ≥5 nets, ≥75% routing completion, board 10–500 mm, ≤20% off-board components. Results in `data/training/`: raw `.kicad_pcb` files, per-file `score.json`, `visited.json` (resumability), `candidates.json` (index of passing boards). Requires `pip install requests` and `GITHUB_TOKEN` env var.
8. **GNN for net ordering + strategy selection** — input: netlist graph + placement, output: strategy tag per net + routing order
9. **GNN for auto-placement** — predict component positions from netlist graph. Training data: KiCad boards with coordinates.
10. **RL training loop** — benchmark score becomes reward function: `Q = completion × wire_efficiency × via_efficiency`
11. **Zone decomposition** — GNN predicts coarse tile assignment, A* does detailed routing within constraints

### Product
10. **Web frontend** — backend: auth + storage (S3, no DB). All routing in browser.
11. **Board size restriction** for free tier
12. **Copper fills UI** — pour is implemented in router, needs UI exposure
13. **Export — Phase 1 (done)**: `KiCadWriter` appends routed traces and vias as `(segment ...)` / `(via ...)` nodes into a copy of the `.kicad_pcb` file → user opens in KiCad → File → Plot → Gerbers → ZIP → upload to fab. Copper pour export (zone fills) is Phase 2.
14. **Export — Phase 2 (web product)**: build a native Gerber generator (RS-274X). Web users won't have KiCad. Minimum files: `F.Cu.gbr`, `B.Cu.gbr`, `Edge.Cuts.gbr`, `drill.drl` (Excellon). One week of careful work — soldermask openings, aperture definitions, pad shapes all need handling. Do this when building the web frontend.

## Code Standards

This codebase applies SOLID principles and Yegor Bugayenko's Elegant Objects philosophy.
Every new module and refactor must follow these rules. When in doubt, the rule applies.

### SOLID

**Single Responsibility** — one module, one job.
- `router/drc.py` only checks design rules. It never routes.
- `router/quality.py` only computes metrics. It never routes or checks rules.
- `Router` routes. It does not print reports, compute metrics, or run DRC.
- `Grid` stores state and answers queries. It does not know about routing strategy.
- When a function in one module needs data from another, pass it as a parameter — do not reach in.

**Open / Closed** — extend without modifying.
- `route_all(nets_ordered=None)` is the GNN injection point. Future ML ordering passes in a list; the router runs unchanged.
- New design rule presets are added by creating a new `DesignRules(...)` constant — not by touching existing presets or Router logic.
- New DRC check = new case in `run_drc()` + new `ViolationType` value. Nothing else changes.

**Liskov Substitution** — not yet relevant (no inheritance hierarchy), but: do not add `isinstance` checks. If you feel the urge, add a method to the object instead.

**Interface Segregation** — keep function signatures narrow.
- `quality_report(our_wire_by_name, our_pct, our_vias, ref_wire_by_name, ref_vias)` takes five typed scalars, not a raw `dict`. Callers are explicit about what they provide.
- Do not pass "god objects" (full result dicts, full board objects) when only two fields are needed.

**Dependency Inversion** — depend on abstractions, not concretions.
- `Router` accepts a `DesignRules` instance — it never imports a specific preset.
- `run_drc` accepts any router object that exposes `.routed` and `.pour_masks` — not a concrete `Router`.
- CLI scripts (`kicad_demo.py`, `benchmark.py`) are the composition root. They wire up the concrete objects and call into the library.

### Elegant Objects (Yegor Bugayenko)

**Immutable data objects** — use `@dataclass(frozen=True)` for all value types.
```python
# ✓ correct
@dataclass(frozen=True)
class DRCViolation:
    type: ViolationType
    description: str

# ✗ wrong — mutable, fields can be clobbered after construction
@dataclass
class DRCViolation:
    ...
```
Applies to: `DesignRules`, `DRCViolation`, `QualityReport`, `Pad`, `Net`, `Component`.
`Grid` and `Router` are stateful by nature — they are NOT frozen, but mutate only through their own methods.

**No public static functions** — algorithms live on the class that uses them.
```python
# ✓ correct — owned by the class that uses it
class Router:
    @staticmethod
    def _mst_pad_order(pads) -> List[int]: ...

# ✗ wrong — module-level function with no owner
def _mst_pad_order(pads) -> List[int]: ...
```

**No boolean flags that alter control flow** — replace with logging or separate methods.
```python
# ✓ correct — stdlib logging; callers set the level
logger = logging.getLogger(__name__)
logger.info("Routing complete: %d/%d nets", done, total)

# ✗ wrong — flag toggles behaviour inside the object
def __init__(self, ..., verbose=True):
    self.verbose = verbose
...
if self.verbose:
    print(...)
```

**No private attribute access across class boundaries** — expose a query method instead.
```python
# ✓ correct — Grid owns its pad set; callers ask
grid.is_pad_cell(layer, row, col)

# ✗ wrong — reaches into Grid's internals
(layer, row, col) in grid._pad_cells
```

**`__str__` on value objects** — typed objects render themselves; callers never build strings manually.
```python
# ✓ correct
str(violation)  # → "SHORT_CIRCUIT: net 1 vs net 2 at (3.0,5.0)mm layer 0"

# ✗ wrong — caller reconstructing the string
f"{violation.type.name}: {violation.description}"
```

**Constructors build complete objects** — no `init()`, no two-phase construction, no fields that start as `None` and get filled in later (exception: `Router.global_router` and `Router._cost_map` are set after `route_all()` for inspection — this is an intentional tradeoff for debuggability, not a pattern to copy).

### Logging, not printing

- Use `logging.getLogger(__name__)` inside library modules (`router/`). Never `print()`.
- CLI entry points (`kicad_demo.py`, `benchmark.py`) call `logging.basicConfig(level=logging.INFO)` so users see progress.
- Tests see no output by default — no handler means no noise.

### Enums over strings for categories

```python
# ✓ correct — type-safe, IDE-completable, exhaustive-checkable
v.type == ViolationType.SHORT_CIRCUIT

# ✗ wrong — typo-prone, no static checking
v.startswith("SHORT_CIRCUIT")
```

## What NOT to Do

**Domain rules**
- Don't mark component body obstacles — they wall in pads. Use courtyard data when available.
- Don't use `\S+` in the tokenizer regex — it eats closing parentheses.
- Don't route GND/power nets as traces on dense boards — use copper pour.
- Don't mention "India" or "developing countries" in preset names.
- Don't call `mark_edge_keepout` after `mark_pad` — pads near edges will be lost.
- Don't set via_cost the same for all presets — home etch needs high cost, online fab needs low.

**Code quality rules**
- Don't add `verbose` / `debug` boolean flags — use `logging` instead.
- Don't access `_private` attributes of another class — add a public query method.
- Don't pass raw dicts as typed arguments — use a frozen dataclass.
- Don't put module-level functions in `router/` that belong on a class — make them `@staticmethod`.
- Don't match violation types with `str.startswith()` — compare `ViolationType` enum values.
- Don't add `isinstance` checks for dispatch — add a method to the object.
- Don't add `print()` inside `router/` library modules — use `logging.getLogger(__name__)`.
- Don't create mutable dataclasses for value types — use `@dataclass(frozen=True)`.

## Training Data for GNN
Every `.kicad_pcb` file with components placed on the board is a training example:
- Input: netlist graph (components as nodes, nets as edges with pad counts)
- Output: component x/y positions (for placement GNN)
- Output: net routing order + wire paths (for routing policy GNN)

Need ~500–1000 boards. Sources: KiCad GitHub repos, OSHPark public designs, KiCad demo library.
