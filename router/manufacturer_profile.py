"""
Manufacturer profiles for DRC and routing preset selection.

Each profile encodes:
  - A DesignRules instance (routing config — trace width, via dims, clearance, via cost)
  - DRC-only constraints that are checked post-route but don't affect the routing grid
    (hole sizes, hole-to-hole clearance, silkscreen rules)

Source URLs are documented so values can be verified and updated when fabs change specs.
All values are minimums unless noted as maximums.

Merge strategy: ManufacturerProfile.merge(*profiles) applies strictest-wins —
  max of all minimums, min of all maximums.
This is the only safe strategy: a constraint that is too loose silently produces scrap.
"""

from dataclasses import dataclass
from typing import Optional

from .design_rules import DesignRules


@dataclass(frozen=True)
class ManufacturerProfile:
    name: str
    source_url: str          # capabilities page — update this when specs change

    # Routing config for this fab tier (feeds Router directly)
    design_rules: DesignRules

    # DRC constraints: via geometry
    min_via_diameter_mm: float   # full via pad = drill + 2×annular

    # DRC constraints: through-holes
    min_pth_drill_mm: float      # plated through-hole minimum drill
    max_pth_drill_mm: float      # plated through-hole maximum drill
    min_npth_drill_mm: float     # non-plated hole minimum drill

    # DRC constraints: spacing
    min_hole_to_hole_mm: float   # centre-to-centre for holes on different nets

    # DRC constraints: silkscreen
    min_silk_text_height_mm: float
    min_silk_clearance_mm: float  # silkscreen to copper pad

    @staticmethod
    def merge(*profiles: 'ManufacturerProfile') -> 'ManufacturerProfile':
        """
        Combine multiple profiles using strictest-wins.

        For every minimum constraint: take the maximum across all profiles.
        For every maximum constraint: take the minimum across all profiles.
        The resulting profile satisfies every input profile simultaneously.
        """
        if len(profiles) == 1:
            return profiles[0]

        drs = [p.design_rules for p in profiles]
        merged_dr = DesignRules(
            name=" + ".join(p.name for p in profiles),
            resolution_mm=max(d.resolution_mm for d in drs),
            clearance_mm=max(d.clearance_mm for d in drs),
            component_clearance_mm=max(d.component_clearance_mm for d in drs),
            via_drill_mm=max(d.via_drill_mm for d in drs),
            via_annular_mm=max(d.via_annular_mm for d in drs),
            via_cost=max(d.via_cost for d in drs),
            edge_clearance_mm=max(d.edge_clearance_mm for d in drs),
        )
        return ManufacturerProfile(
            name=" + ".join(p.name for p in profiles),
            source_url="",
            design_rules=merged_dr,
            min_via_diameter_mm=max(p.min_via_diameter_mm for p in profiles),
            min_pth_drill_mm=max(p.min_pth_drill_mm for p in profiles),
            max_pth_drill_mm=min(p.max_pth_drill_mm for p in profiles),
            min_npth_drill_mm=max(p.min_npth_drill_mm for p in profiles),
            min_hole_to_hole_mm=max(p.min_hole_to_hole_mm for p in profiles),
            min_silk_text_height_mm=max(p.min_silk_text_height_mm for p in profiles),
            min_silk_clearance_mm=max(p.min_silk_clearance_mm for p in profiles),
        )


# ------------------------------------------------------------------
# PCBWay
# Source: github.com/pcbway/PCBWay-Design-Rules (official PCBWay repo)
# Disclaimer from PCBWay: "All statements without guarantee."
# Verify against: pcbway.com/capabilities.html
# ------------------------------------------------------------------

PCBWAY_2L = ManufacturerProfile(
    name="PCBWay — 2-layer standard (1oz copper)",
    source_url="https://github.com/pcbway/PCBWay-Design-Rules",
    design_rules=DesignRules(
        name="PCBWay 2-layer",
        resolution_mm=0.127,
        clearance_mm=0.127,
        component_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_annular_mm=0.1,    # pad = 0.3 + 2×0.1 = 0.5mm
        via_cost=4.0,
        edge_clearance_mm=0.3,
    ),
    min_via_diameter_mm=0.5,
    min_pth_drill_mm=0.2,
    max_pth_drill_mm=6.35,
    min_npth_drill_mm=0.5,
    min_hole_to_hole_mm=0.5,
    min_silk_text_height_mm=0.8,
    min_silk_clearance_mm=0.15,
)

PCBWAY_4L = ManufacturerProfile(
    name="PCBWay — 4-layer advanced (1oz/0.5oz copper)",
    source_url="https://github.com/pcbway/PCBWay-Design-Rules",
    design_rules=DesignRules(
        name="PCBWay 4-layer",
        resolution_mm=0.09,
        clearance_mm=0.09,
        component_clearance_mm=0.15,
        via_drill_mm=0.15,
        via_annular_mm=0.075,  # pad = 0.15 + 2×0.075 = 0.3mm
        via_cost=3.0,
        edge_clearance_mm=0.3,
    ),
    min_via_diameter_mm=0.3,
    min_pth_drill_mm=0.2,
    max_pth_drill_mm=6.35,
    min_npth_drill_mm=0.5,
    min_hole_to_hole_mm=0.5,
    min_silk_text_height_mm=0.8,
    min_silk_clearance_mm=0.15,
)

# ------------------------------------------------------------------
# JLCPCB
# Source: github.com/labtroll/KiCad-DesignRules (community, verified
#         against JLCPCB capabilities page jlcpcb.com/capabilities/pcb-capabilities)
# ------------------------------------------------------------------

JLCPCB_2L = ManufacturerProfile(
    name="JLCPCB — 2-layer standard",
    source_url="https://jlcpcb.com/capabilities/pcb-capabilities",
    design_rules=DesignRules(
        name="JLCPCB 2-layer",
        resolution_mm=0.127,
        clearance_mm=0.127,
        component_clearance_mm=0.2,
        via_drill_mm=0.3,
        via_annular_mm=0.1,    # pad = 0.5mm
        via_cost=4.0,
        edge_clearance_mm=0.3,
    ),
    min_via_diameter_mm=0.5,
    min_pth_drill_mm=0.2,
    max_pth_drill_mm=6.3,
    min_npth_drill_mm=0.5,
    min_hole_to_hole_mm=0.5,
    min_silk_text_height_mm=1.0,   # JLCPCB requires 1mm; PCBWay allows 0.8mm
    min_silk_clearance_mm=0.15,
)

JLCPCB_4L = ManufacturerProfile(
    name="JLCPCB — 4-layer advanced",
    source_url="https://jlcpcb.com/capabilities/pcb-capabilities",
    design_rules=DesignRules(
        name="JLCPCB 4-layer",
        resolution_mm=0.09,
        clearance_mm=0.09,
        component_clearance_mm=0.15,
        via_drill_mm=0.2,
        via_annular_mm=0.075,  # pad = 0.2 + 2×0.075 = 0.35mm
        via_cost=3.0,
        edge_clearance_mm=0.3,
    ),
    min_via_diameter_mm=0.35,
    min_pth_drill_mm=0.2,
    max_pth_drill_mm=6.3,
    min_npth_drill_mm=0.5,
    min_hole_to_hole_mm=0.5,
    min_silk_text_height_mm=1.0,
    min_silk_clearance_mm=0.15,
)

# ------------------------------------------------------------------
# Zbotic (zbotic.in — Moxie Supply Pvt Ltd, Pune)
# Source: zbotic.in/pcb-technical-design-guidelines/
# ------------------------------------------------------------------

ZBOTIC_2L = ManufacturerProfile(
    name="Zbotic — 2-layer (0.127mm / 5mil)",
    source_url="https://zbotic.in/pcb-technical-design-guidelines/",
    design_rules=DesignRules(
        name="Zbotic 2-layer",
        resolution_mm=0.127,
        clearance_mm=0.127,
        component_clearance_mm=0.2,
        via_drill_mm=0.15,
        via_annular_mm=0.13,
        via_cost=4.0,
        edge_clearance_mm=0.3,
    ),
    min_via_diameter_mm=0.41,   # 0.15 + 2×0.13
    min_pth_drill_mm=0.2,
    max_pth_drill_mm=6.3,
    min_npth_drill_mm=0.5,
    min_hole_to_hole_mm=0.5,
    min_silk_text_height_mm=0.8,
    min_silk_clearance_mm=0.15,
)

ZBOTIC_4L = ManufacturerProfile(
    name="Zbotic — 4+ layer (0.1mm / 4mil)",
    source_url="https://zbotic.in/pcb-technical-design-guidelines/",
    design_rules=DesignRules(
        name="Zbotic 4-layer",
        resolution_mm=0.1,
        clearance_mm=0.1,
        component_clearance_mm=0.15,
        via_drill_mm=0.15,
        via_annular_mm=0.1,
        via_cost=3.0,
        edge_clearance_mm=0.3,
    ),
    min_via_diameter_mm=0.35,   # 0.15 + 2×0.1
    min_pth_drill_mm=0.2,
    max_pth_drill_mm=6.3,
    min_npth_drill_mm=0.5,
    min_hole_to_hole_mm=0.5,
    min_silk_text_height_mm=0.8,
    min_silk_clearance_mm=0.15,
)

ALL_PROFILES = [PCBWAY_2L, PCBWAY_4L, JLCPCB_2L, JLCPCB_4L, ZBOTIC_2L, ZBOTIC_4L]
