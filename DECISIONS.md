# Architecture Decision Log

Tracks major design choices, why they were made, what was rejected and why.
Purpose: avoid re-litigating settled decisions; allow revisiting if circumstances change.

---

## D1 — Routing executor: A* (not RL, not ILP, not pure neural)

**Decision**: A* is the detailed routing executor. ML never draws traces.

**Options considered**:

| Option | Why rejected |
|--------|-------------|
| Lee's algorithm (BFS maze router) | A* strictly dominates — same correctness, faster via heuristic |
| Integer Linear Programming (ILP) | Provably optimal but NP-hard, intractable above ~50 nets, unusable on real boards |
| Simulated annealing | No correctness guarantees, slow convergence, hard to tune |
| Pure RL drawing traces | Enormous action space (1.2M cells/step), no short-circuit guarantees, sample-inefficient, academic papers only work on toy grids |
| Neural net predicting trace geometry | Fragile, no DRC guarantees, geometry similarity is wrong metric (many valid solutions exist) |

**Why A***: guarantees no shorts by construction, scales to real boards, 8-directional with via support already implemented, octile heuristic is near-optimal. The execution problem is solved — ML should plan, not execute.

**Revisit if**: someone publishes a neural router with provable DRC guarantees and better completion than A* on real boards.

---

## D2 — Planner architecture: build order

**Decision**: implement in stages, each validating the next.

### Option A — PathFinder alone (no ML)
Negotiated congestion: route all nets allowing temporary overlaps, iteratively inflate cost of conflicted areas, repeat until clean.
- **Status**: TODO as baseline — implement before GNN work
- **Why not end goal**: no learning, same fixed strategy on every board, can't adapt to fab profile
- **Value**: significant improvement over current greedy A*, provides baseline to measure GNN improvement against
- **When to revisit**: if GNN experiments show no improvement over PathFinder, fall back to this

### Option B — Message-passing GNN + A* (one-shot planning)
GNN encodes netlist graph, predicts net ordering + zone assignments once, A* executes.
- **Status**: first ML milestone — implement after PathFinder baseline
- **Why chosen first**: simple, fast to train, works with ~1000 boards, validates that learned planning helps
- **Limitation**: one-shot — if plan is wrong, no recovery mechanism
- **Architecture**: GAT (Graph Attention Network) or GCNConv via PyTorch Geometric
- **When to revisit**: if one-shot planning is sufficient for target board complexity, no need to go to D

### Option C — Graph Transformer + A*
Replace GNN encoder with global attention — every net attends to every other net.
- **Status**: candidate for placement model (item 9 in CLAUDE.md)
- **Why not first**: O(N²) attention slow on large graphs, needs more training data, overkill for net ordering
- **Why for placement**: placement needs global context ("U2 should be near U7 because they share 3 nets") that local message-passing misses
- **Architecture**: TransformerConv (PyG) or GPS layer
- **When to revisit**: after Option B is validated; use for placement GNN

### Option D — Temporal Transformer over GNN chunk states + A* (target architecture)
GNN encodes each chunk state → Transformer attends over full chunk history → planning head outputs zone assignments + net order + rip-up mask → A* executes chunk → repeat.
- **Status**: target architecture, build after B and C are working
- **Why chosen**: only architecture that handles replanning from failure history; attention over chunk sequence enables "chunk 4 failure caused by chunk 2 decision" credit assignment
- **Three components**:
  1. **Netlist encoder (GNN)**: graph topology → node embeddings (fixed per board)
  2. **State encoder (GNN per chunk)**: current board state → state embedding
  3. **Temporal attention (Transformer)**: [state_1..state_k] → replanning context
- **Chunk size**: adaptive, triggered by congestion threshold not fixed N — chunk size emerges from board complexity
- **Rip-up**: planning head outputs probability per routed net of being ripped up in next chunk
- **Research claim**: no published system combines learned replanner + correct executor in iterative feedback loop
- **When to revisit**: GPS architecture (Rampášek 2022, arxiv 2205.12454) combines message-passing + attention per layer — candidate to replace separate GNN + Transformer components

### Option E — GPS (General Powerful Scalable) architecture
Combines message-passing + Transformer attention in each layer. State of the art on graph benchmarks (2022).
- **Status**: candidate to replace GNN encoder in Option D
- **Why not now**: newer, less intuitive, harder to debug during early experiments
- **PyG support**: `GPSConv` — native
- **When to revisit**: when implementing Option D encoder

---

## D3 — Per-fab models (not one generalised model)

**Decision**: train a separate model per manufacturer profile.

**Why**: routing strategies are fundamentally different across fabs:
- HOME_ETCH: vias are expensive (hand-drilled) → model learns to avoid layer switches
- JLCPCB_2L: vias are cheap (machine-drilled) → model learns to use vias freely for congestion escape
- A generalised model learns the average strategy, which is wrong for every specific fab

**Implementation**: fab profile TOML files (already exist) become training configuration. New fab = new TOML + retrain = new model.

**Revisit if**: a conditioning approach (fab profile as input embedding) is shown to match per-fab model quality — would reduce model count. Try this in Option B experiments.

---

## D4 — Reward function design

**Decision**: hard constraints gate to R=0, soft objectives as weighted product.

**Why product not sum**: sum allows model to ignore DRC by maximising completion alone. Product means any factor near zero drags whole reward to zero — forces model to care about all objectives simultaneously.

**Hard constraints** (any violation → R = 0.0, episode terminates):
- Short circuits
- Routing completion below threshold (e.g. 95%)
- Power nets (VCC/GND) unconnected
- Trace width below fab minimum
- Clearance below fab minimum
- Via drill below fab minimum
- Annular ring below fab minimum
- Via aspect ratio exceeds fab maximum
- Trace current capacity exceeded (IPC-2221)
- Board edge violation

**Soft objectives** (weighted product, each in [0,1]):
```
R = completion²              # squared — most important, penalise incompleteness hard
  × wire_efficiency          # min(ref_wire / our_wire, 1.0)
  × via_efficiency           # min(ref_vias / our_vias, 1.0)
  × drc_score                # 1 - (soft_violations / total_nets)
  × thermal_score            # 1 - (thermal_warnings / total_nets)  [later phase]
  × dfm_score                # 1 - (dfm_warnings / total_checks)    [later phase]
  × si_score                 # 1 - (si_warnings / hs_nets)          [later phase]
```

**Per-chunk intermediate rewards** (for iterative routing, item 10):
```
reward_k = nets_connected_k - congestion_increase_k - hard_violations_k × penalty
total = Σ reward_k × discount^k + R_final
```
Discounted intermediates: early chunks matter but final DRC score dominates.

**Revisit if**: completion² weighting causes model to over-optimise completion at expense of DRC — tune exponent or add explicit DRC weight.

---

## D5 — Evaluation methodology

**Decision**: DRC-score based evaluation, not geometry matching.

**Why not geometry matching**: many valid routing solutions exist for any board. Comparing trace coordinates to human reference penalises correct-but-different solutions. Human routing may be suboptimal.

**Why DRC score**: objective, reproducible, maps directly to "does this board work and can it be manufactured."

**Benchmark structure**:
- 80/20 train/test split, stratified by net count band (<50, 50-150, 150+)
- Test set: strip traces from copy of board → run GNN+A* → evaluate
- Absolute metrics: completion%, short circuits (must be 0), DRC violations
- Relative metrics: wire length vs original, via count vs original, completion vs original human routing
- Generalisation test: train on crawled boards, test on KiCad official demo boards (unseen)

**Headline claim**: "GNN-guided A* achieves X% completion with zero short circuits, outperforming FreeRouting on DRC score by Y% on held-out boards."

---

## D6 — Library choice: PyTorch Geometric (PyG)

**Decision**: PyG for all GNN/Graph Transformer work.

**Why**: native support for heterogeneous graphs (different node types: components, nets, pads), GAT/GCNConv/TransformerConv/GPSConv all available, active development, good documentation, integrates with PyTorch training loop.

**Alternatives considered**: DGL (Deep Graph Library) — similar capability, less community momentum in PCB/EDA space. NetworkX — CPU only, not suitable for training.

**Revisit if**: memory issues on large graphs — PyG Cluster/Saint samplers for mini-batching, or switch to DGL if PyG has scaling issues.
