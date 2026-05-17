"""
DesignRules — routing configuration passed to Router.

These are the parameters the router uses during A* pathfinding:
  resolution_mm        = trace width (1 cell = 1 trace width)
  clearance_mm         = minimum gap between traces of different nets
  component_clearance_mm = minimum keepout around component bodies
  via_drill_mm / via_annular_mm = via geometry (recorded for DRC/export)
  via_cost             = A* cost of a layer change (high = avoid vias)
  edge_clearance_mm    = copper keepout from board edge

Manufacturer presets live in router/profiles/*.toml and are loaded by
router/manufacturer_profile.py. Import from there, not here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DesignRules:
    name: str
    resolution_mm: float
    clearance_mm: float
    component_clearance_mm: float
    via_drill_mm: float
    via_annular_mm: float
    via_cost: float = 8.0
    edge_clearance_mm: float = 0.3

    @property
    def clearance_cells(self) -> int:
        """Grid cells to enforce as clearance between nets."""
        return max(1, round(self.clearance_mm / self.resolution_mm))

    @property
    def component_clearance_cells(self) -> int:
        return max(1, round(self.component_clearance_mm / self.resolution_mm))

    def summary(self) -> str:
        return (
            f"{self.name}\n"
            f"  trace width : {self.resolution_mm:.3f} mm  "
            f"({self.resolution_mm / 0.0254:.0f} mil)\n"
            f"  clearance   : {self.clearance_mm:.3f} mm  "
            f"({self.clearance_mm / 0.0254:.0f} mil)\n"
            f"  via drill   : {self.via_drill_mm:.3f} mm\n"
            f"  via pad     : {self.via_drill_mm + 2*self.via_annular_mm:.3f} mm"
        )
