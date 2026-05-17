from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, List

import numpy as np

from .board import Grid
from .design_rules import DesignRules
from .netlist import Net

if TYPE_CHECKING:
    from .manufacturer_profile import ManufacturerProfile
    from .router import Router


class ViolationType(Enum):
    # Grid / routing checks (run_drc)
    OPEN = auto()
    EDGE_CLEARANCE = auto()
    SHORT_CIRCUIT = auto()
    PAD_CLEARANCE = auto()
    # Profile compatibility checks (check_profile_compatibility)
    TRACE_TOO_NARROW = auto()
    VIA_DRILL_TOO_SMALL = auto()
    VIA_DIAMETER_TOO_SMALL = auto()
    ANNULAR_RING_TOO_NARROW = auto()


@dataclass(frozen=True)
class DRCViolation:
    type: ViolationType
    description: str

    def __str__(self) -> str:
        return f"{self.type.name}: {self.description}"


def run_drc(grid: Grid, nets: List[Net], router: 'Router', rules: DesignRules) -> List[DRCViolation]:
    """
    Post-route grid DRC. Returns typed violations:
      OPEN           — unrouted net
      EDGE_CLEARANCE — trace within edge keepout zone
      SHORT_CIRCUIT  — two routed traces of different nets adjacent
                       (true routing bug; pad-to-pad adjacency excluded)
      PAD_CLEARANCE  — pad of one net adjacent to pad/trace of another
                       (placement issue, not a routing bug)
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

    # Boolean mask for cells inside the edge keepout band
    edge_mask = np.zeros((rows, cols), dtype=bool)
    edge_mask[:ec, :] = True
    edge_mask[rows - ec:, :] = True
    edge_mask[:, :ec] = True
    edge_mask[:, cols - ec:] = True

    for layer in range(grid.num_layers):
        layer_grid = g[layer]
        # Candidates: any positive net_id inside the edge band
        rr, cc = np.where(edge_mask & (layer_grid > 0))
        for r, c in zip(rr.tolist(), cc.tolist()):
            cell = int(layer_grid[r, c])
            if cell in pour_ids or grid.is_pad_cell(layer, r, c):
                continue
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


def check_profile_compatibility(
    rules: DesignRules,
    profile: 'ManufacturerProfile',
) -> List[DRCViolation]:
    """
    Check whether the routing DesignRules satisfy the manufacturer's capabilities.

    This is a configuration check, not a grid scan — it runs once and answers:
    "Were the routing parameters chosen compatible with what this fab can produce?"

    Returns violations for any routing parameter that falls below the fab's minimum.
    An empty list means the routing config is within spec for this manufacturer.
    """
    violations: List[DRCViolation] = []
    dr = profile.design_rules

    if rules.resolution_mm < dr.resolution_mm:
        violations.append(DRCViolation(
            ViolationType.TRACE_TOO_NARROW,
            f"trace width {rules.resolution_mm:.3f}mm < {profile.name} minimum "
            f"{dr.resolution_mm:.3f}mm",
        ))

    if rules.via_drill_mm < dr.via_drill_mm:
        violations.append(DRCViolation(
            ViolationType.VIA_DRILL_TOO_SMALL,
            f"via drill {rules.via_drill_mm:.3f}mm < {profile.name} minimum "
            f"{dr.via_drill_mm:.3f}mm",
        ))

    if rules.via_annular_mm < dr.via_annular_mm:
        violations.append(DRCViolation(
            ViolationType.ANNULAR_RING_TOO_NARROW,
            f"annular ring {rules.via_annular_mm:.3f}mm < {profile.name} minimum "
            f"{dr.via_annular_mm:.3f}mm",
        ))

    via_diameter = rules.via_drill_mm + 2 * rules.via_annular_mm
    if via_diameter < profile.min_via_diameter_mm:
        violations.append(DRCViolation(
            ViolationType.VIA_DIAMETER_TOO_SMALL,
            f"via pad {via_diameter:.3f}mm < {profile.name} minimum "
            f"{profile.min_via_diameter_mm:.3f}mm",
        ))

    return violations
