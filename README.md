# PCB Auto-Router

A Python proof-of-concept for AI-assisted PCB routing. Import a KiCad board file, get it auto-routed in seconds.

**Status:** Active research / proof-of-concept. Not yet production-ready.

---

## What It Does

- Reads `.kicad_pcb` files (KiCad 7, 8, and 10 format)
- Auto-routes all nets using A* pathfinding on a 2-layer grid
- Supports copper pour (GND flood fill) on any layer
- Visualises the result as a two-panel image (top copper / bottom copper)
- Benchmarks against the existing routing in a file — measures completion %, wire length efficiency, via count, and DRC violations
- DRC checks: open nets, edge clearance, short circuits, pad clearance
- Manufacturer profiles with `merge()` for strictest-wins constraint checking

What it does **not** do (yet): schematic capture, auto-placement, Gerber export.

---

## Quick Start

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install numpy matplotlib

# Route a KiCad board (outputs demo_result.png)
python kicad_demo.py path/to/your_board.kicad_pcb

# Run the benchmark across all demo boards
python benchmark.py
```

---

## Example Output

Two-panel view — top copper (F.Cu) and bottom copper (B.Cu) side by side.  
Legend below the board. GND copper pour shown as semi-transparent fill.

---

## Manufacturer Profiles

Profiles live in `router/profiles/*.toml`. Add a new manufacturer by adding one `.toml` file — no Python code needed.

| Profile | Trace / Clearance | Via drill | Via cost | Target |
|---------|------------------|-----------|----------|--------|
| `HOME_ETCH` | 1.0 mm | 0.8 mm | High | Toner transfer / UV home etching |
| `PCBWAY_2L` | 0.127 mm | 0.3 mm | Low | PCBWay 2-layer standard |
| `PCBWAY_4L` | 0.1 mm | 0.2 mm | Low | PCBWay 4-layer advanced |
| `JLCPCB_2L` | 0.127 mm | 0.3 mm | Low | JLCPCB 2-layer standard |
| `JLCPCB_4L` | 0.1 mm | 0.2 mm | Low | JLCPCB 4-layer advanced |
| `ZBOTIC_2L` | 0.15 mm | 0.3 mm | Low | ZBOTIC 2-layer |
| `ZBOTIC_4L` | 0.1 mm | 0.2 mm | Low | ZBOTIC 4-layer |

Change `PROFILE` at the top of `kicad_demo.py` to target a different fab.  
Use `ManufacturerProfile.merge(a, b)` to combine constraints (strictest-wins).

---

## Benchmark Results

Tested against KiCad demo boards using the same component placements, routing from scratch with a 0.5 mm benchmark grid (speed-optimised — use a manufacturer profile for real DRC).

| Board | Nets | Our routed | Our unrouted | KiCad routed | KiCad unrouted | Wire vs KiCad | Shorts | Quality |
|-------|------|-----------|-------------|-------------|---------------|---------------|--------|---------|
| multichannel_mixer | 80 | 79 (98.8%) | 1 | 79 (98.8%) | 1 | −7.0% shorter | ✓ | 75.9 |
| complex_hierarchy | 52 | 50 (96.2%) | 2 | 49 (94.2%) | 3 | −22.6% shorter | ✓ | 76.9 |
| ecc83-pp | 13 | 9 (69.2%) | 4 | 8 (61.5%) | 5 | −23.5% shorter | ✓ | 55.4 |
| ecc83-pp_v2 | 13 | 9 (69.2%) | 4 | 9 (69.2%) | 4 | −26.3% shorter | ✓ | 55.4 |
| interf_u | 173 | 102 (59.0%) | 71 | 110 (63.6%) | 63 | −8.2% shorter | ✓ | 47.2 |
| tinytapeout | 114 | 71 (62.3%) | 43 | 108 (94.7%) | 6 | −18.8% shorter | ✓ | 49.8 |
| pic_programmer | 111 | 34 (30.6%) | 77 | 0 (0%) | 111 | n/a | ✓ | — |
| CM5_MINIMA_3 | 220 | 47 (21.4%) | 173 | 96 (43.6%) | 124 | −14.6% shorter | ✓ | 17.1 |

**Zero short circuits on every board.** On nets we complete, our A* consistently produces shorter wire than the human/FreeRouting reference. Dense boards (CM5, tinytapeout) are limited by routing capacity — they need a finer grid (0.127 mm) or layer-aware global routing to improve completion.

---

## Architecture

```
.kicad_pcb
    → KiCadBoard parser (handles KiCad 7/8 + KiCad 10 format)
    → Grid (2D numpy array per copper layer)
        - EMPTY / OBSTACLE / net_id per cell
        - Edge keepout applied as obstacle border
        - Clearance enforced at query time (numpy slice)
    → GlobalRouter (tile-level congestion planning → cost_map)
    → Router
        - MST pad ordering (Prim's) — trunk-and-branch topology
        - A* pathfinding — 8-directional, via support
        - Rip-and-retry for failed nets
        - Copper pour (BFS flood-fill) for GND nets
    → DRC (open nets, edge clearance, short circuits, pad clearance)
    → Benchmark / quality scoring vs KiCad reference
```

---

## File Structure

```
router/
  board.py              Grid class — 2D numpy array per layer
  astar.py              A* pathfinding — 8-directional, via support
  router.py             Router — MST ordering, rip-and-retry, copper pour
  global_router.py      Tile-level congestion planning and cost map
  netlist.py            Pad / Net / Component frozen dataclasses
  design_rules.py       DesignRules dataclass (fields only — no presets)
  manufacturer_profile.py  ManufacturerProfile, load_all_profiles(), merge()
  drc.py                ViolationType, DRCViolation, run_drc(), check_profile_compatibility()
  quality.py            QualityReport, quality_report()
  kicad_parser.py       .kicad_pcb parser (KiCad 7/8 + 10)
  profiles/             Manufacturer specs as TOML files (one file per fab)
  __init__.py           POUR_NET_NAMES frozenset
visualize.py            Two-panel matplotlib visualisation (F.Cu / B.Cu)
kicad_demo.py           Route a single board from a .kicad_pcb file
benchmark.py            Benchmark all demo boards, compare vs KiCad reference
demo.py                 Synthetic 5-net demo board
crawl_training_data.py  Crawl GitHub for KiCad files → score → GNN training set
tests/                  pytest test suite
results/                Benchmark output images
kicad-demo/             KiCad demo boards (local copy)
data/                   Synthetic test boards
data/training/          GNN training data (downloaded by crawl_training_data.py)
CLAUDE.md               Project context for AI assistant sessions
```

---

## Roadmap

### Phase 1 — Router improvements (current)
- [x] A* routing with 2-layer via support
- [x] MST trunk-and-branch for multi-pin nets
- [x] Global routing (tile congestion map)
- [x] Copper pour (GND flood fill)
- [x] Edge keepout enforcement
- [x] Benchmark + quality scoring vs KiCad reference
- [x] DRC: open nets, edge clearance, short circuits, pad clearance
- [x] Manufacturer profiles (TOML, merge, check_profile_compatibility)
- [ ] Power net spine routing (dedicated trunk for VCC/vbias)
- [ ] Layer-aware global routing (assign nets to preferred layers)
- [ ] Negotiated congestion (PathFinder-style)

### Phase 2 — GNN-assisted routing
- [ ] Collect training data — `crawl_training_data.py` crawls GitHub (`kicad`, `kicad-pcb`, `open-hardware` topics + `extension:kicad_pcb` code search), scores each board (routing completion, component placement, board size), saves passing boards to `data/training/` with per-file score reports
- [ ] GNN model: netlist graph → net ordering + strategy tags
- [ ] Zone decomposition predicted by GNN
- [ ] RL training loop: benchmark score → reward → GNN weight update

### Phase 3 — Auto-placement
- [ ] GNN model: netlist graph → component positions
- [ ] Training data: KiCad boards with coordinates

### Phase 4 — Web product
- [ ] Web frontend (all routing in browser via WASM or API)
- [ ] Auth + S3 storage (no DB)
- [ ] Board size restriction for free tier
- [ ] KiCad export: write routed traces as `(segment ...)` / `(via ...)` nodes
- [ ] Gerber export (RS-274X native generator)

---

## Key Observations

- **Via cost must match the fab process.** Hand-drilled vias (home etch) are expensive; machine-drilled vias at JLCPCB are essentially free. Using a high via cost on dense boards causes routing failures because the router can't escape congestion without switching layers.
- **MST ordering beats sequential ordering** for multi-pin nets — power rails with many pads route 30–50% shorter by connecting the closest pair first and branching from there.
- **GND copper pour is essential** — routing GND as individual traces on a dense board fails. Flooding unused copper is both more reliable and more electrically sound.
- **On routable boards, our A* produces shorter wire than human routing.** The quality gap is about completion rate, not routing quality per se.

---

## License

To be decided. Intended as freeware for hobbyists.
