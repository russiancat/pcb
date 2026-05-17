import heapq
import logging
import math
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np

from .astar import astar, astar_to_net
from .board import EMPTY, Grid
from .design_rules import DesignRules
from .global_router import GlobalRouter
from .netlist import Net

logger = logging.getLogger(__name__)


class Router:
    """
    Routes all nets on a Grid using A* with rip-and-retry.

    Strategy:
      1. Global routing pass — tile-level congestion map, nets ordered
         least-congested first (or use injected order for GNN integration).
      2. Detailed A* pass guided by congestion cost map.
      3. Rip-and-retry — failed nets retry up to max_iterations times
         with progressively halved congestion penalty.

    Design rules (clearance, via cost) come from a DesignRules preset.
    """

    def __init__(self, grid: Grid, nets: List[Net],
                 rules: DesignRules,
                 max_iterations: int = 3,
                 tile_size_mm: float = 5.0):
        self.grid = grid
        self.nets = nets
        self.rules = rules
        self.max_iterations = max_iterations
        self.tile_size_mm = tile_size_mm
        self.via_cost = rules.via_cost

        self.routed: Dict[int, List[List[Tuple]]] = {}
        self.vias: Dict[int, List[Tuple[int, int]]] = {}
        self.pour_masks: Dict[int, Dict[int, np.ndarray]] = {}

        self.global_router: Optional[GlobalRouter] = None
        self._cost_map = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mst_pad_order(pads) -> List[int]:
        """Return pad indices in Prim's MST order (Euclidean distance).

        Seeds with the two closest pads, then greedily adds each remaining
        pad nearest to any pad already in the tree.
        """
        n = len(pads)
        if n <= 2:
            return list(range(n))

        pos = [(p.x, p.y) for p in pads]

        best = float('inf')
        seed_i, seed_j = 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                d = math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
                if d < best:
                    best, seed_i, seed_j = d, i, j

        in_tree = [False] * n
        in_tree[seed_i] = True
        in_tree[seed_j] = True
        order = [seed_i, seed_j]

        heap: List = []
        for k in range(n):
            if not in_tree[k]:
                for seed in (seed_i, seed_j):
                    d = math.hypot(pos[seed][0] - pos[k][0], pos[seed][1] - pos[k][1])
                    heapq.heappush(heap, (d, k))

        while heap and len(order) < n:
            dist, k = heapq.heappop(heap)
            if in_tree[k]:
                continue
            in_tree[k] = True
            order.append(k)
            for j in range(n):
                if not in_tree[j]:
                    d = math.hypot(pos[k][0] - pos[j][0], pos[k][1] - pos[j][1])
                    heapq.heappush(heap, (d, j))

        return order

    def _mark_path(self, path: List[Tuple], net_id: int) -> List[Tuple[int, int]]:
        via_list = []
        for i, (col, row, layer) in enumerate(path):
            self.grid.mark_trace(col, row, layer, net_id)
            if i > 0 and path[i][2] != path[i - 1][2]:
                via_list.append((col, row))
        return via_list

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def route_net(self, net: Net, cost_map=None) -> bool:
        if len(net.pads) < 2:
            return True

        cc = self.rules.clearance_cells
        mst_idx = self._mst_pad_order(net.pads)
        pads     = [net.pads[i]                    for i in mst_idx]
        pad_grid = [self.grid.mm_to_grid(p.x, p.y) for p in pads]

        all_paths: List[List[Tuple]] = []
        all_vias:  List[Tuple[int, int]] = []

        start = (pad_grid[0][0], pad_grid[0][1], pads[0].layer)
        path  = astar(self.grid, start,
                      pad_grid[1][0], pad_grid[1][1],
                      net.net_id, self.via_cost, cc, cost_map)
        if path is None:
            return False
        all_vias.extend(self._mark_path(path, net.net_id))
        all_paths.append(path)

        for i in range(2, len(pads)):
            new_start = (pad_grid[i][0], pad_grid[i][1], pads[i].layer)
            path = astar_to_net(self.grid, new_start,
                                pad_grid[:i], net.net_id,
                                self.via_cost, cc, cost_map)
            if path is None:
                return False
            all_vias.extend(self._mark_path(path, net.net_id))
            all_paths.append(path)

        self.routed[net.net_id] = all_paths
        self.vias[net.net_id]   = all_vias
        return True

    def route_all(self, nets_ordered: Optional[List[Net]] = None) -> List[Net]:
        """
        Two-level routing.

        nets_ordered: optional pre-computed routing order for GNN integration.
                      When None, the GlobalRouter computes the order via
                      tile-level congestion planning.
        """
        gr = GlobalRouter(self.grid, tile_size_mm=self.tile_size_mm)
        gr_ordered = gr.plan_all(self.nets)
        cost_map = gr.build_cost_map()
        self.global_router = gr
        self._cost_map = cost_map
        logger.info("Global routing: %s", gr.stats())

        routing_order = nets_ordered if nets_ordered is not None else gr_ordered

        failed = self._route_batch(routing_order, cost_map)

        penalty_scale = 1.0
        for iteration in range(self.max_iterations):
            if not failed:
                break
            penalty_scale *= 0.5
            scaled_map = cost_map * penalty_scale if cost_map is not None else None
            logger.info(
                "Rip-and-retry %d: %d net(s) failed (congestion penalty ×%.2f)",
                iteration + 1, len(failed), penalty_scale,
            )
            for net in failed:
                self.grid.clear_net(net.net_id)
                self.routed.pop(net.net_id, None)
                self.vias.pop(net.net_id, None)
            failed = self._route_batch(failed, scaled_map)

        total = len(self.nets)
        done  = len(self.routed)
        pct   = 100 * done // total if total else 0
        logger.info("Routing complete: %d/%d nets (%d%%)", done, total, pct)
        return failed

    def _route_batch(self, nets: List[Net], cost_map=None) -> List[Net]:
        failed = []
        for net in nets:
            if not self.route_net(net, cost_map):
                self.grid.clear_net(net.net_id)
                self.routed.pop(net.net_id, None)
                self.vias.pop(net.net_id, None)
                failed.append(net)
        return failed

    def copper_pour(self, net_id: int, layer: int = 0) -> int:
        """Flood-fill unused copper on layer with net_id (copper pour).

        BFS from cells already belonging to net_id, expanding to all
        reachable empty cells that satisfy clearance from other nets.
        Returns number of new cells filled.
        """
        cc = self.rules.clearance_cells

        before = (self.grid.grid[layer] == net_id).copy()

        queue: deque = deque()
        visited = np.zeros((self.grid.rows, self.grid.cols), dtype=bool)
        for row in range(self.grid.rows):
            for col in range(self.grid.cols):
                if self.grid.grid[layer, row, col] == net_id:
                    visited[row, col] = True
                    queue.append((col, row))

        if not queue:
            return 0

        filled = 0
        while queue:
            col, row = queue.popleft()
            for dc, dr in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nc, nr = col + dc, row + dr
                if not self.grid.is_valid(nc, nr, layer) or visited[nr, nc]:
                    continue
                visited[nr, nc] = True
                if self.grid.is_passable(nc, nr, layer, net_id, cc):
                    self.grid.grid[layer, nr, nc] = net_id
                    filled += 1
                    queue.append((nc, nr))

        if filled:
            after = self.grid.grid[layer] == net_id
            self.pour_masks.setdefault(net_id, {})[layer] = after & ~before

        return filled
