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

## Design Rules Presets

| Preset | Trace width | Clearance | Via cost | Target |
|--------|------------|-----------|----------|--------|
| `HOME_ETCH` | 1.0 mm | 1.0 mm | High | Toner transfer / UV home etching |
| `LOCAL_FAB_BASIC` | 0.5 mm | 0.5 mm | Medium | Local fab, older equipment |
| `LOCAL_FAB_MODERN` | 0.3 mm | 0.3 mm | Medium | Local fab, modern equipment |
| `HOBBYIST_ONLINE` | 0.25 mm | 0.25 mm | Low | JLCPCB / PCBWay hobbyist |
| `PROFESSIONAL` | 0.127 mm | 0.127 mm | Low | Tight professional specs |

Default is `LOCAL_FAB_BASIC`. Change `RULES` at the top of `kicad_demo.py`.

---

## Benchmark Results

Tested against 8 KiCad demo boards using the same component placements but routing from scratch.

| Board | Nets | Our completion | Wire vs reference |
|-------|------|---------------|-------------------|
| multichannel_mixer | 80 | 98.8% | **−8.2% shorter** |
| complex_hierarchy | 52 | 96.2% | **−21.3% shorter** |
| ecc83-pp | 13 | 69.2% | **−23.5% shorter** |
| interf_u | 173 | 59.0% | −9.3% shorter |
| CM5_MINIMA | 220 | 18.6% | (dense board, needs global routing) |
| tinytapeout | 114 | 52.6% | (296 parts, high density) |

On nets we complete, our A* consistently produces **shorter wire than the human/FreeRouting reference**. Dense boards are limited by the lack of a global routing stage.

---

## Architecture

```
.kicad_pcb
    → KiCadBoard parser (handles KiCad 7/8 + KiCad 10 format)
    → Grid (2D numpy array per copper layer)
        - EMPTY / OBSTACLE / net_id per cell
        - Edge keepout applied as obstacle border
        - Clearance enforced at query time (numpy slice)
    → Router
        - MST pad ordering (Prim's) — trunk-and-branch topology
        - A* pathfinding — 8-directional, via support
        - Rip-and-retry for failed nets
        - Copper pour (BFS flood-fill) for GND nets
    → Benchmark / DRC
        - Net completion, wire length, via count vs reference
        - DRC: open nets, edge clearance, short circuits
```

---

## Roadmap

### Phase 1 — Router improvements (current)
- [x] A* routing with 2-layer via support
- [x] MST trunk-and-branch for multi-pin nets
- [x] Copper pour (GND flood fill)
- [x] Edge keepout enforcement
- [x] Benchmark + quality scoring vs KiCad reference
- [ ] Fix short circuits on dense boards (rip-and-retry partial trace cleanup)
- [ ] Zone-based global routing (tile overlay for dense boards)
- [ ] Power net spine routing (dedicated trunk for VCC/vbias)

### Phase 2 — GNN-assisted routing
- [ ] Collect training data (KiCad boards from public repos)
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
- [ ] Gerber export

---

## File Structure

```
router/
  board.py          Grid class
  astar.py          A* pathfinding
  router.py         Router (MST, copper pour, rip-and-retry)
  netlist.py        Pad / Net / Component data classes
  design_rules.py   DesignRules presets
  kicad_parser.py   .kicad_pcb parser (KiCad 7/8 + 10)
visualize.py        Two-panel matplotlib visualisation
kicad_demo.py       Route a single board
benchmark.py        Benchmark all demo boards
demo.py             Synthetic 5-net demo
results/            Benchmark output images
kicad-demo/         KiCad demo boards (local copy)
data/               Synthetic test boards
CLAUDE.md           Project context for AI assistant sessions
```

---

## Key Observations

- **Via cost must match the fab process.** Hand-drilled vias (home etch) are expensive; machine-drilled vias at JLCPCB are essentially free. Using a high via cost on dense boards causes routing failures because the router can't escape congestion without switching layers.
- **MST ordering beats sequential ordering** for multi-pin nets — power rails with many pads route 30–50% shorter by connecting the closest pair first and branching from there.
- **GND copper pour is essential** — routing GND as individual traces on a dense board fails. Flooding unused copper is both more reliable and more electrically sound.
- **On routable boards, our A* produces shorter wire than human routing.** The quality gap is about completion rate, not routing quality per se.

---

## License

To be decided. Intended as freeware for hobbyists.
