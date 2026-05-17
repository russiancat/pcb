"""
A* pathfinder for PCB routing.

Move set: 8-directional (4 orthogonal + 4 diagonal).
  - Orthogonal cost : 1.0
  - Diagonal cost   : √2 ≈ 1.414  (no corner-cutting through obstacles)
  - Via cost        : configurable (default 20× orthogonal)

Heuristic: octile distance — admissible and consistent for 8-directional grids.

Clearance: passed through to Grid.is_passable(); rejects cells that are too
close to a foreign net.  See board.py for implementation.
"""

import heapq
import math
from typing import List, Optional, Tuple

from .board import Grid

SQRT2 = math.sqrt(2)

# (delta_col, delta_row, move_cost)
MOVES = [
    (0,  1, 1.0),   # N
    (0, -1, 1.0),   # S
    (1,  0, 1.0),   # E
    (-1, 0, 1.0),   # W
    (1,  1, SQRT2), # NE
    (1, -1, SQRT2), # SE
    (-1, 1, SQRT2), # NW
    (-1,-1, SQRT2), # SW
]


def _octile(col: int, row: int, ec: int, er: int) -> float:
    """Octile distance — exact cost for 8-directional movement."""
    dx, dy = abs(col - ec), abs(row - er)
    return (dx + dy) + (SQRT2 - 2) * min(dx, dy)


def _reconstruct(came_from: dict, state: Tuple) -> List[Tuple]:
    path = []
    s = state
    while s is not None:
        path.append(s)
        s = came_from[s]
    return path[::-1]


def _neighbors(grid: Grid, col: int, row: int, layer: int,
               net_id: int, clearance_cells: int):
    """
    Yield (new_col, new_row, new_layer, cost) for all valid moves.
    Diagonal moves require both adjacent orthogonal cells to be passable
    (prevents cutting through diagonal gaps between obstacles).
    """
    for dc, dr, cost in MOVES:
        nc, nr = col + dc, row + dr
        if not grid.is_passable(nc, nr, layer, net_id, clearance_cells):
            continue
        # Corner-cutting check for diagonals
        if dc != 0 and dr != 0:
            if (not grid.is_passable(col + dc, row, layer, net_id, 0) or
                    not grid.is_passable(col, row + dr, layer, net_id, 0)):
                continue
        yield nc, nr, layer, cost


def astar(grid: Grid,
          start: Tuple[int, int, int],
          end_col: int, end_row: int,
          net_id: int,
          via_cost: float = 20.0,
          clearance_cells: int = 0,
          cost_map=None) -> Optional[List[Tuple]]:
    """
    Route from start=(col, row, layer) to (end_col, end_row) on any layer.

    cost_map: optional float32 array [layer, row, col] — extra cost added
    to each move entering a cell (from global router congestion map).

    The target pad is pre-marked with net_id so it is passable, and can be
    reached from either layer (placing a via if needed).
    Returns list of (col, row, layer) or None if unreachable.
    """
    end_states = frozenset(
        (end_col, end_row, l) for l in range(grid.num_layers)
    )

    def h(col: int, row: int) -> float:
        return _octile(col, row, end_col, end_row)

    counter = 0
    sc, sr, sl = start
    open_heap = [(h(sc, sr), counter, start)]
    g: dict = {start: 0.0}
    came_from: dict = {start: None}
    closed: set = set()

    while open_heap:
        _, _, state = heapq.heappop(open_heap)
        if state in closed:
            continue
        closed.add(state)

        if state in end_states:
            return _reconstruct(came_from, state)

        col, row, layer = state

        # Lateral moves (8-directional on same layer)
        for nc, nr, nl, cost in _neighbors(grid, col, row, layer,
                                           net_id, clearance_cells):
            ns = (nc, nr, nl)
            if ns in closed:
                continue
            extra = float(cost_map[nl, nr, nc]) if cost_map is not None else 0.0
            new_g = g[state] + cost + extra
            if new_g < g.get(ns, 1e18):
                g[ns] = new_g
                came_from[ns] = state
                counter += 1
                heapq.heappush(open_heap,
                               (new_g + h(nc, nr), counter, ns))

        # Via: switch layer (stay at same grid position)
        for nl in range(grid.num_layers):
            if nl == layer:
                continue
            if not grid.is_passable(col, row, nl, net_id, clearance_cells):
                continue
            ns = (col, row, nl)
            if ns in closed:
                continue
            extra = float(cost_map[nl, row, col]) if cost_map is not None else 0.0
            new_g = g[state] + via_cost + extra
            if new_g < g.get(ns, 1e18):
                g[ns] = new_g
                came_from[ns] = state
                counter += 1
                heapq.heappush(open_heap,
                               (new_g + h(col, row), counter, ns))

    return None


def astar_to_net(grid: Grid,
                 start: Tuple[int, int, int],
                 ref_points: List[Tuple[int, int]],
                 net_id: int,
                 via_cost: float = 20.0,
                 clearance_cells: int = 0,
                 cost_map=None) -> Optional[List[Tuple]]:
    """
    Route from start to any existing cell already marked with net_id.
    Used to connect the 3rd, 4th, ... pin to the existing trace tree.

    ref_points: (col, row) of previously routed pads — used for heuristic.
    cost_map: optional float32 array [layer, row, col] from global router.
    """
    def h(col: int, row: int) -> float:
        return min(_octile(col, row, rc, rr) for rc, rr in ref_points)

    counter = 0
    sc, sr, sl = start
    open_heap = [(h(sc, sr), counter, start)]
    g: dict = {start: 0.0}
    came_from: dict = {start: None}
    closed: set = set()

    while open_heap:
        _, _, state = heapq.heappop(open_heap)
        if state in closed:
            continue
        closed.add(state)

        col, row, layer = state

        # Reached an existing net cell (not the start pad itself)
        if state != start and grid.grid[layer, row, col] == net_id:
            return _reconstruct(came_from, state)

        for nc, nr, nl, cost in _neighbors(grid, col, row, layer,
                                           net_id, clearance_cells):
            ns = (nc, nr, nl)
            if ns in closed:
                continue
            extra = float(cost_map[nl, nr, nc]) if cost_map is not None else 0.0
            new_g = g[state] + cost + extra
            if new_g < g.get(ns, 1e18):
                g[ns] = new_g
                came_from[ns] = state
                counter += 1
                heapq.heappush(open_heap,
                               (new_g + h(nc, nr), counter, ns))

        for nl in range(grid.num_layers):
            if nl == layer:
                continue
            if not grid.is_passable(col, row, nl, net_id, clearance_cells):
                continue
            ns = (col, row, nl)
            if ns in closed:
                continue
            extra = float(cost_map[nl, row, col]) if cost_map is not None else 0.0
            new_g = g[state] + via_cost + extra
            if new_g < g.get(ns, 1e18):
                g[ns] = new_g
                came_from[ns] = state
                counter += 1
                heapq.heappush(open_heap,
                               (new_g + h(col, row), counter, ns))

    return None
