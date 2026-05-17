from dataclasses import dataclass
from enum import Enum, auto
from typing import List

import numpy as np

from .board import Grid
from .design_rules import DesignRules


class ViolationType(Enum):
    OPEN = auto()
    EDGE_CLEARANCE = auto()
    SHORT_CIRCUIT = auto()
    PAD_CLEARANCE = auto()


@dataclass(frozen=True)
class DRCViolation:
    type: ViolationType
    description: str

    def __str__(self) -> str:
        return f"{self.type.name}: {self.description}"


def run_drc(grid: Grid, nets: list, router, rules: DesignRules) -> List[DRCViolation]:
    """
    Post-route DRC. Returns typed violations categorised as:
      OPEN           — unrouted net
      EDGE_CLEARANCE — trace within edge keepout zone
      SHORT_CIRCUIT  — two routed traces of different nets adjacent
                       (true routing bug; pad-to-pad adjacency is excluded)
      PAD_CLEARANCE  — pad of one net adjacent to pad/trace of another
                       (placement concern, not a routing bug)
    """
    violations: List[DRCViolation] = []

    routed_ids = set(router.routed.keys()) | set(router.pour_masks.keys())
    pour_ids = set(router.pour_masks.keys())

    for net in nets:
        if net.net_id not in routed_ids:
            violations.append(DRCViolation(
                ViolationType.OPEN,
                f"{net.name} ({len(net.pads)} pads unconnected)",
            ))

    ec = max(1, round(rules.edge_clearance_mm / rules.resolution_mm))
    g = grid.grid
    rows, cols = grid.rows, grid.cols
    for layer in range(grid.num_layers):
        layer_grid = g[layer]
        for r in range(rows):
            for c in range(cols):
                cell = layer_grid[r, c]
                if cell <= 0 or cell in pour_ids or grid.is_pad_cell(layer, r, c):
                    continue
                if r < ec or r >= rows - ec or c < ec or c >= cols - ec:
                    x, y = grid.grid_to_mm(c, r)
                    violations.append(DRCViolation(
                        ViolationType.EDGE_CLEARANCE,
                        f"net {cell} trace at ({x:.1f},{y:.1f})mm layer {layer}",
                    ))

    def _classify_adj(layer: int, r1: int, c1: int, r2: int, c2: int) -> None:
        net_a = g[layer, r1, c1]
        net_b = g[layer, r2, c2]
        if net_a <= 0 or net_b <= 0 or net_a == net_b:
            return
        x, y = grid.grid_to_mm(c1, r1)
        vtype = (ViolationType.PAD_CLEARANCE
                 if grid.is_pad_cell(layer, r1, c1) or grid.is_pad_cell(layer, r2, c2)
                 else ViolationType.SHORT_CIRCUIT)
        violations.append(DRCViolation(
            vtype,
            f"net {net_a} vs net {net_b} at ({x:.1f},{y:.1f})mm layer {layer}",
        ))

    for layer in range(grid.num_layers):
        lg = g[layer]
        hor = np.where((lg[:, :-1] > 0) & (lg[:, 1:] > 0) & (lg[:, :-1] != lg[:, 1:]))
        for r, c in zip(hor[0], hor[1]):
            _classify_adj(layer, r, c, r, c + 1)
        ver = np.where((lg[:-1, :] > 0) & (lg[1:, :] > 0) & (lg[:-1, :] != lg[1:, :]))
        for r, c in zip(ver[0], ver[1]):
            _classify_adj(layer, r, c, r + 1, c)

    return violations
