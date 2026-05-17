"""
Design rules presets for common PCB manufacturers.

In this router, grid resolution = trace width (one cell = one trace width).
Clearance is enforced as additional cells around each trace during routing.

Changing the preset changes:
  - Grid resolution (= trace width)
  - Clearance between different nets
  - Component body keepout distance
  - Via dimensions (recorded for DRC/export; not yet simulated in grid)
"""

from dataclasses import dataclass


@dataclass
class DesignRules:
    name: str
    # Grid resolution also sets the trace width (1 cell = 1 trace width)
    resolution_mm: float
    # Minimum gap between traces of different nets
    clearance_mm: float
    # Minimum keepout around component bodies
    component_clearance_mm: float
    # Via geometry
    via_drill_mm: float
    via_annular_mm: float   # ring width; total via pad = drill + 2*annular
    # Via cost in A* units (orthogonal steps equivalent).
    # High = router avoids vias; low = router uses them freely to escape congestion.
    # Scale to the manufacturing process: hand-drilled vias are genuinely expensive,
    # machine-drilled are nearly free at JLCPCB / PCBWay.
    via_cost: float = 8.0
    # Minimum clearance to board edge (copper keepout)
    edge_clearance_mm: float = 0.3

    @property
    def clearance_cells(self) -> int:
        """Number of grid cells to enforce as clearance between nets."""
        return max(1, round(self.clearance_mm / self.resolution_mm))

    @property
    def component_clearance_cells(self) -> int:
        return max(1, round(self.component_clearance_mm / self.resolution_mm))

    def summary(self) -> str:
        return (
            f"{self.name}\n"
            f"  trace width : {self.resolution_mm:.2f} mm  "
            f"({self.resolution_mm / 0.0254:.0f} mil)\n"
            f"  clearance   : {self.clearance_mm:.2f} mm  "
            f"({self.clearance_mm / 0.0254:.0f} mil)\n"
            f"  via drill   : {self.via_drill_mm:.2f} mm\n"
            f"  via pad     : {self.via_drill_mm + 2*self.via_annular_mm:.2f} mm"
        )


# ------------------------------------------------------------------
# Presets
# ------------------------------------------------------------------

HOME_ETCH = DesignRules(
    name="Home etching (toner transfer / UV)",
    resolution_mm=1.0,
    clearance_mm=1.0,
    component_clearance_mm=1.0,
    via_drill_mm=1.2,
    via_annular_mm=0.6,
    via_cost=25.0,       # hand-drilled vias are genuinely expensive — avoid them
    edge_clearance_mm=0.5,
)

LOCAL_FAB_BASIC = DesignRules(
    name="Local fab — basic (older equipment)",
    resolution_mm=0.5,
    clearance_mm=0.5,
    component_clearance_mm=0.5,
    via_drill_mm=0.8,
    via_annular_mm=0.4,
    via_cost=8.0,
    edge_clearance_mm=0.3,
)

LOCAL_FAB_MODERN = DesignRules(
    name="Local fab — modern equipment",
    resolution_mm=0.3,
    clearance_mm=0.3,
    component_clearance_mm=0.3,
    via_drill_mm=0.6,
    via_annular_mm=0.3,
    via_cost=5.0,
    edge_clearance_mm=0.3,
)

HOBBYIST_ONLINE = DesignRules(
    name="Online fab — JLCPCB / PCBWay / Aisler (hobbyist)",
    resolution_mm=0.25,
    clearance_mm=0.25,
    component_clearance_mm=0.3,
    via_drill_mm=0.4,
    via_annular_mm=0.2,
    via_cost=4.0,        # vias nearly free at JLCPCB/PCBWay
    edge_clearance_mm=0.3,
)

PROFESSIONAL = DesignRules(
    name="Online fab — JLCPCB / PCBWay (professional / tight)",
    resolution_mm=0.127,
    clearance_mm=0.127,
    component_clearance_mm=0.2,
    via_drill_mm=0.3,
    via_annular_mm=0.15,
    via_cost=3.0,
    edge_clearance_mm=0.2,
)
