"""
Write routed traces and vias back into a .kicad_pcb file.

Phase 1: segments and vias only. Copper pour (zone fills) require
KiCad's zone format and are deferred to Phase 2.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .board import Grid
from .design_rules import DesignRules

logger = logging.getLogger(__name__)

_LAYER_NAMES: Dict[int, str] = {0: "F.Cu", 1: "B.Cu"}


@dataclass(frozen=True)
class _Segment:
    x1: float; y1: float
    x2: float; y2: float
    layer_name: str
    width: float
    net_id: int


@dataclass(frozen=True)
class _Via:
    x: float; y: float
    size: float
    drill: float
    net_id: int


class KiCadWriter:
    """
    Appends routed traces and vias to a .kicad_pcb file.

    Construct with the post-routing state; call write() to produce a new
    file.  The source file is never modified.
    """

    def __init__(self, grid: Grid, router, rules: DesignRules,
                 origin_x: float = 0.0, origin_y: float = 0.0):
        self._segments = self._build_segments(
            grid, router.routed, rules, origin_x, origin_y
        )
        self._vias = self._build_vias(
            grid, router.vias, rules, origin_x, origin_y
        )
        logger.info("KiCadWriter: %d segments, %d vias ready",
                    len(self._segments), len(self._vias))

    def write(self, source_path: str, output_path: str) -> Tuple[int, int]:
        """
        Copy source_path → output_path with routed segments and vias appended.

        Returns (segment_count, via_count).
        """
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        idx = text.rfind(")")
        if idx == -1:
            raise ValueError(
                f"Not a valid KiCad file (no closing ')'): {source_path}"
            )

        lines = [f"  {self._render_segment(s)}" for s in self._segments]
        lines += [f"  {self._render_via(v)}" for v in self._vias]
        block = "\n".join(lines)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text[:idx])
            if block:
                f.write("\n" + block + "\n")
            f.write(")\n")

        logger.info("KiCadWriter: wrote %d segments, %d vias → %s",
                    len(self._segments), len(self._vias), output_path)
        return len(self._segments), len(self._vias)

    # ------------------------------------------------------------------

    @staticmethod
    def _build_segments(grid: Grid, routed: dict, rules: DesignRules,
                        ox: float, oy: float) -> List[_Segment]:
        segments: List[_Segment] = []
        width = rules.resolution_mm
        for net_id, paths in routed.items():
            for path in paths:
                prev = None
                for cell in path:
                    col, row, layer = cell
                    if prev is not None:
                        pc, pr, pl = prev
                        if pl == layer and (pc, pr) != (col, row):
                            x1, y1 = grid.grid_to_mm(pc, pr)
                            x2, y2 = grid.grid_to_mm(col, row)
                            segments.append(_Segment(
                                x1=x1 + ox, y1=y1 + oy,
                                x2=x2 + ox, y2=y2 + oy,
                                layer_name=_LAYER_NAMES[layer],
                                width=width,
                                net_id=net_id,
                            ))
                    prev = cell
        return segments

    @staticmethod
    def _build_vias(grid: Grid, vias: dict, rules: DesignRules,
                    ox: float, oy: float) -> List[_Via]:
        result: List[_Via] = []
        size = rules.via_drill_mm + 2.0 * rules.via_annular_mm
        for net_id, positions in vias.items():
            for col, row in positions:
                x, y = grid.grid_to_mm(col, row)
                result.append(_Via(
                    x=x + ox, y=y + oy,
                    size=size,
                    drill=rules.via_drill_mm,
                    net_id=net_id,
                ))
        return result

    @staticmethod
    def _render_segment(s: _Segment) -> str:
        return (
            f'(segment'
            f' (start {s.x1:.6f} {s.y1:.6f})'
            f' (end {s.x2:.6f} {s.y2:.6f})'
            f' (width {s.width:.6f})'
            f' (layer "{s.layer_name}")'
            f' (net {s.net_id})'
            f' (tstamp "{uuid.uuid4()}"))'
        )

    @staticmethod
    def _render_via(v: _Via) -> str:
        return (
            f'(via'
            f' (at {v.x:.6f} {v.y:.6f})'
            f' (size {v.size:.6f})'
            f' (drill {v.drill:.6f})'
            f' (layers "F.Cu" "B.Cu")'
            f' (net {v.net_id})'
            f' (tstamp "{uuid.uuid4()}"))'
        )
