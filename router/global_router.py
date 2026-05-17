"""
Zone-based global router (coarse planning pass).

Divides the board into square tiles and plans each net through the
least-congested tile corridor before the detailed A* pass runs.

Output: cost_map[layer, row, col]  — soft penalty array consumed by A*.
Cells in over-capacity tiles cost more, nudging traces toward less-
congested corridors without hard-blocking them (graceful fallback).

Two-level flow
--------------
1. GlobalRouter.plan_all(nets)   — tile-level MST + Dijkstra, O(nets * tile_count)
2. GlobalRouter.build_cost_map() — projects tile congestion → per-cell floats
3. Router passes cost_map to astar() for every detailed route call
"""

import heapq
import math
from typing import Dict, List, Set, Tuple

import numpy as np

from .board import Grid
from .netlist import Net

SQRT2 = math.sqrt(2)

_TILE_MOVES = [
    (0,  1, 1.0),
    (0, -1, 1.0),
    (1,  0, 1.0),
    (-1, 0, 1.0),
    (1,  1, SQRT2),
    (1, -1, SQRT2),
    (-1, 1, SQRT2),
    (-1,-1, SQRT2),
]


class GlobalRouter:
    """Coarse tile-based global router.

    Parameters
    ----------
    grid               : the routing grid (for geometry, not cell data)
    tile_size_mm       : size of one square tile in mm
    capacity           : nets-per-tile before congestion penalty kicks in
                         (auto-computed from tile size and design rules if 0)
    penalty_per_excess : extra A* cost added to every cell in an
                         over-capacity tile, per excess net
    """

    def __init__(self, grid: Grid, tile_size_mm: float = 5.0,
                 capacity: int = 0,
                 penalty_per_excess: float = 0.3):
        self.grid = grid
        self.tile_size = tile_size_mm
        self.penalty = penalty_per_excess

        self.tile_cols = max(1, math.ceil(grid.width_mm  / tile_size_mm))
        self.tile_rows = max(1, math.ceil(grid.height_mm / tile_size_mm))

        # Grid cells that fit along one tile edge (for cost-map projection)
        self._cells_per_tile = max(1, round(tile_size_mm / grid.resolution))

        # Auto capacity: how many traces fit through one tile side
        if capacity > 0:
            self.capacity = capacity
        else:
            # Trace pitch = 2 cells (1 trace + 1 clearance minimum)
            self.capacity = max(2, self._cells_per_tile // 2)

        # congestion[layer, tile_row, tile_col] = number of nets planned through
        self.congestion = np.zeros(
            (grid.num_layers, self.tile_rows, self.tile_cols), dtype=np.int32
        )

        # net_id -> set of (tile_col, tile_row) tiles in its global route
        self.net_tiles: Dict[int, Set[Tuple[int, int]]] = {}

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def mm_to_tile(self, x_mm: float, y_mm: float) -> Tuple[int, int]:
        tc = int(x_mm / self.tile_size)
        tr = int(y_mm / self.tile_size)
        return (max(0, min(tc, self.tile_cols - 1)),
                max(0, min(tr, self.tile_rows - 1)))

    # ------------------------------------------------------------------
    # Tile-level A*: find least-congested path between two tiles
    # ------------------------------------------------------------------

    def _tile_astar(self, src: Tuple[int, int],
                    dst: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Dijkstra on the tile graph; uses current congestion as extra cost."""
        if src == dst:
            return [src]

        def h(tc, tr):
            dx, dy = abs(tc - dst[0]), abs(tr - dst[1])
            return (dx + dy) + (SQRT2 - 2) * min(dx, dy)

        counter = 0
        open_heap = [(h(*src), counter, src)]
        g: Dict[Tuple, float] = {src: 0.0}
        came_from: Dict[Tuple, object] = {src: None}
        closed: Set = set()

        while open_heap:
            _, _, state = heapq.heappop(open_heap)
            if state in closed:
                continue
            closed.add(state)
            if state == dst:
                path = []
                s = state
                while s is not None:
                    path.append(s)
                    s = came_from[s]
                return path[::-1]

            tc, tr = state
            for dtc, dtr, cost in _TILE_MOVES:
                ntc, ntr = tc + dtc, tr + dtr
                if not (0 <= ntc < self.tile_cols and 0 <= ntr < self.tile_rows):
                    continue
                ns = (ntc, ntr)
                if ns in closed:
                    continue
                # Soft penalty for already-congested tiles
                cong = int(self.congestion[:, ntr, ntc].max())
                extra = max(0, cong - self.capacity) * 2.0
                ng = g[state] + cost + extra
                if ng < g.get(ns, 1e18):
                    g[ns] = ng
                    came_from[ns] = state
                    counter += 1
                    heapq.heappush(open_heap, (ng + h(ntc, ntr), counter, ns))

        # Fallback: straight Manhattan path if A* fails (shouldn't happen)
        path = []
        tc, tr = src
        while tc != dst[0]:
            path.append((tc, tr))
            tc += 1 if dst[0] > tc else -1
        while tr != dst[1]:
            path.append((tc, tr))
            tr += 1 if dst[1] > tr else -1
        path.append(dst)
        return path

    # ------------------------------------------------------------------
    # Plan a single net at tile level (MST-style)
    # ------------------------------------------------------------------

    def plan_net(self, net: Net) -> Set[Tuple[int, int]]:
        """Plan coarse tile path, update congestion, return tile set."""
        if len(net.pads) < 2:
            return set()

        pad_tiles = [self.mm_to_tile(p.x, p.y) for p in net.pads]

        all_tiles: Set[Tuple[int, int]] = {pad_tiles[0]}
        in_tree: List[Tuple[int, int]] = [pad_tiles[0]]
        remaining = list(pad_tiles[1:])

        while remaining:
            # Prim's: pick the remaining tile closest (Manhattan) to any in-tree tile
            best_d = float('inf')
            best_i = 0
            best_src = in_tree[0]
            for i, pt in enumerate(remaining):
                for src in in_tree:
                    d = abs(pt[0] - src[0]) + abs(pt[1] - src[1])
                    if d < best_d:
                        best_d, best_i, best_src = d, i, src

            dst_tile = remaining.pop(best_i)
            path = self._tile_astar(best_src, dst_tile)
            for tile in path:
                all_tiles.add(tile)
            in_tree.append(dst_tile)

        # Increment congestion on all layers (net could route on either)
        for tc, tr in all_tiles:
            self.congestion[:, tr, tc] += 1

        self.net_tiles[net.net_id] = all_tiles
        return all_tiles

    # ------------------------------------------------------------------
    # Plan all nets + derive routing order
    # ------------------------------------------------------------------

    def plan_all(self, nets: List[Net]) -> List[Net]:
        """
        Plan all nets globally.  Returns nets sorted for optimal detailed
        routing: least-congested-path nets first (they take simple direct
        paths, leaving contested corridors open for constrained nets).
        """
        # First pass: plan in wirelength order so short simple nets define
        # the base congestion map before long nets are planned
        nets_by_wl = sorted(nets, key=lambda n: n.estimated_wirelength())
        for net in nets_by_wl:
            self.plan_net(net)

        # Second: order for detailed routing — nets whose planned path
        # sits in the least-congested tiles go first
        def _max_congestion(net: Net) -> int:
            tiles = self.net_tiles.get(net.net_id, set())
            if not tiles:
                return 0
            return max(int(self.congestion[:, tr, tc].max())
                       for tc, tr in tiles)

        return sorted(nets, key=lambda n: (_max_congestion(n), n.estimated_wirelength()))

    # ------------------------------------------------------------------
    # Build the per-cell cost map for detailed A*
    # ------------------------------------------------------------------

    def build_cost_map(self) -> np.ndarray:
        """
        Returns cost_map[layer, row, col] (float32).

        Each grid cell in an over-capacity tile receives:
            penalty_per_excess * (congestion - capacity)
        as an additional cost per step for the detailed A* router.
        """
        cpt = self._cells_per_tile
        cost_map = np.zeros(
            (self.grid.num_layers, self.grid.rows, self.grid.cols),
            dtype=np.float32,
        )
        for layer in range(self.grid.num_layers):
            for tr in range(self.tile_rows):
                for tc in range(self.tile_cols):
                    cong = int(self.congestion[layer, tr, tc])
                    if cong <= self.capacity:
                        continue
                    pen = (cong - self.capacity) * self.penalty
                    r0 = tr * cpt
                    r1 = min(r0 + cpt, self.grid.rows)
                    c0 = tc * cpt
                    c1 = min(c0 + cpt, self.grid.cols)
                    cost_map[layer, r0:r1, c0:c1] = pen
        return cost_map

    # ------------------------------------------------------------------
    # Debug / stats
    # ------------------------------------------------------------------

    def stats(self) -> str:
        max_cong  = int(self.congestion.max())
        mean_cong = float(self.congestion[self.congestion > 0].mean()) if self.congestion.any() else 0.0
        hot_tiles = int((self.congestion > self.capacity).sum())
        return (
            f"tiles={self.tile_cols}×{self.tile_rows}  "
            f"capacity={self.capacity}  "
            f"max_cong={max_cong}  mean_cong={mean_cong:.1f}  "
            f"hot_tiles={hot_tiles}"
        )
