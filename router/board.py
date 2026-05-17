import numpy as np
from typing import Set, Tuple

EMPTY = 0
OBSTACLE = -1


class Grid:
    """
    2D grid per copper layer. Each cell stores:
      EMPTY (0)      : free to route
      OBSTACLE (-1)  : physical obstacle (component body, board edge)
      net_id (>0)    : occupied by a routed trace or pad of that net

    Clearance is enforced at query time: is_passable() rejects a cell if
    any cell within clearance_cells belongs to a different net.
    Using numpy slice comparisons keeps this fast.
    """

    def __init__(self, width_mm: float, height_mm: float,
                 resolution: float = 0.25, num_layers: int = 2):
        self.resolution = resolution
        self.num_layers = num_layers
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.cols = int(width_mm / resolution) + 1
        self.rows = int(height_mm / resolution) + 1

        # grid[layer, row, col]
        self.grid = np.zeros((num_layers, self.rows, self.cols), dtype=np.int32)

        # Pad cells survive rip-up
        self._pad_cells: Set[Tuple[int, int, int]] = set()  # (layer, row, col)

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def mm_to_grid(self, x: float, y: float) -> Tuple[int, int]:
        return int(round(x / self.resolution)), int(round(y / self.resolution))

    def grid_to_mm(self, col: int, row: int) -> Tuple[float, float]:
        return col * self.resolution, row * self.resolution

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_pad_cell(self, layer: int, row: int, col: int) -> bool:
        return (layer, row, col) in self._pad_cells

    def is_valid(self, col: int, row: int, layer: int) -> bool:
        return (0 <= col < self.cols and
                0 <= row < self.rows and
                0 <= layer < self.num_layers)

    def is_passable(self, col: int, row: int, layer: int,
                    net_id: int, clearance_cells: int = 0) -> bool:
        """
        A cell is passable for net_id if:
          1. The cell itself is EMPTY or already net_id.
          2. Every cell within clearance_cells (square radius) is also
             EMPTY or net_id — i.e. no foreign net is too close.

        The clearance check uses a numpy slice for speed (no Python loops).
        """
        if not self.is_valid(col, row, layer):
            return False
        cell = self.grid[layer, row, col]
        if cell != EMPTY and cell != net_id:
            return False

        if clearance_cells > 0:
            r0 = max(0, row - clearance_cells)
            r1 = min(self.rows - 1, row + clearance_cells)
            c0 = max(0, col - clearance_cells)
            c1 = min(self.cols - 1, col + clearance_cells)
            region = self.grid[layer, r0:r1 + 1, c0:c1 + 1]
            # Reject only if a FOREIGN NET trace is within clearance.
            # Obstacle cells (-1) are already non-traversable via the check
            # above; they don't count as clearance violations so traces can
            # approach component pads that sit on the body edge.
            if ((region > 0) & (region != net_id)).any():
                return False

        return True

    # ------------------------------------------------------------------
    # Marking
    # ------------------------------------------------------------------

    def mark_edge_keepout(self, cells: int) -> None:
        """Mark a border of `cells` width on all layers as OBSTACLE.

        Call this BEFORE mark_pad() — pad cells will override the obstacle
        when pads happen to sit at the board edge.
        Prevents trace routing from running along the board boundary.
        """
        if cells <= 0:
            return
        c = cells
        self.grid[:, :c, :]           = OBSTACLE   # bottom rows
        self.grid[:, self.rows - c:, :] = OBSTACLE  # top rows
        self.grid[:, :, :c]           = OBSTACLE   # left cols
        self.grid[:, :, self.cols - c:] = OBSTACLE  # right cols

    def mark_obstacle_rect(self, x_mm: float, y_mm: float,
                           w_mm: float, h_mm: float) -> None:
        """Block a rectangular region on all layers."""
        c0, r0 = self.mm_to_grid(x_mm, y_mm)
        c1, r1 = self.mm_to_grid(x_mm + w_mm, y_mm + h_mm)
        c0, c1 = sorted([max(0, c0), min(self.cols - 1, c1)])
        r0, r1 = sorted([max(0, r0), min(self.rows - 1, r1)])
        self.grid[:, r0:r1 + 1, c0:c1 + 1] = OBSTACLE

    def mark_pad(self, x_mm: float, y_mm: float,
                 layer: int, net_id: int) -> Tuple[int, int]:
        """Mark a pad cell. Pad cells survive rip-up."""
        col, row = self.mm_to_grid(x_mm, y_mm)
        if self.is_valid(col, row, layer):
            self.grid[layer, row, col] = net_id
            self._pad_cells.add((layer, row, col))
        return col, row

    def mark_trace(self, col: int, row: int, layer: int, net_id: int) -> None:
        if self.is_valid(col, row, layer):
            self.grid[layer, row, col] = net_id

    def clear_net(self, net_id: int) -> None:
        """Remove routed traces for net_id but preserve its pad markings."""
        mask = self.grid == net_id
        for (l, r, c) in self._pad_cells:
            if self.grid[l, r, c] == net_id:
                mask[l, r, c] = False
        self.grid[mask] = EMPTY
