"""
Manufacturer profiles for DRC and routing preset selection.

Profiles are loaded from router/profiles/*.toml at import time.
Each TOML file is the single source of truth for a manufacturer's capabilities.
To add a new manufacturer: create a new .toml file — no Python changes needed.

Profile structure (see any *.toml for the schema):
  name, source_url
  [design_rules]   — feeds Router directly (trace width, clearance, via dims, via cost)
  [drc]            — post-route checks (hole sizes, hole-to-hole, silkscreen)

Merge strategy: ManufacturerProfile.merge(*profiles) applies strictest-wins.
  max of all minimums, min of all maximums.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .design_rules import DesignRules

PROFILES_DIR = Path(__file__).parent / "profiles"


@dataclass(frozen=True)
class ManufacturerProfile:
    name: str
    source_url: str          # capabilities page — update the .toml when specs change

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
        Combine profiles using strictest-wins.

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
# TOML loader
# ------------------------------------------------------------------

def _load_profile(path: Path) -> ManufacturerProfile:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    dr = data["design_rules"]
    drc = data["drc"]

    design_rules = DesignRules(
        name=data["name"],
        resolution_mm=dr["resolution_mm"],
        clearance_mm=dr["clearance_mm"],
        component_clearance_mm=dr["component_clearance_mm"],
        via_drill_mm=dr["via_drill_mm"],
        via_annular_mm=dr["via_annular_mm"],
        via_cost=dr["via_cost"],
        edge_clearance_mm=dr["edge_clearance_mm"],
    )
    return ManufacturerProfile(
        name=data["name"],
        source_url=data.get("source_url", ""),
        design_rules=design_rules,
        min_via_diameter_mm=drc["min_via_diameter_mm"],
        min_pth_drill_mm=drc["min_pth_drill_mm"],
        max_pth_drill_mm=drc["max_pth_drill_mm"],
        min_npth_drill_mm=drc["min_npth_drill_mm"],
        min_hole_to_hole_mm=drc["min_hole_to_hole_mm"],
        min_silk_text_height_mm=drc["min_silk_text_height_mm"],
        min_silk_clearance_mm=drc["min_silk_clearance_mm"],
    )


def load_all_profiles() -> Dict[str, ManufacturerProfile]:
    """Load all profiles from router/profiles/*.toml. Key = filename stem."""
    return {
        path.stem: _load_profile(path)
        for path in sorted(PROFILES_DIR.glob("*.toml"))
    }


def get_profile(key: str) -> ManufacturerProfile:
    """Load a profile by filename stem (e.g. 'pcbway_2l').
    Raises KeyError with available names if not found.
    """
    if key not in _all:
        available = ", ".join(sorted(_all.keys()))
        raise KeyError(f"Unknown profile {key!r}. Available: {available}")
    return _all[key]


# ------------------------------------------------------------------
# Load at import time and expose as named constants.
# Adding a manufacturer = adding a .toml file; no Python changes needed.
# ------------------------------------------------------------------

_all: Dict[str, ManufacturerProfile] = load_all_profiles()

HOME_ETCH  = _all["home_etch"]
PCBWAY_2L  = _all["pcbway_2l"]
PCBWAY_4L  = _all["pcbway_4l"]
JLCPCB_2L  = _all["jlcpcb_2l"]
JLCPCB_4L  = _all["jlcpcb_4l"]
ZBOTIC_2L  = _all["zbotic_2l"]
ZBOTIC_4L  = _all["zbotic_4l"]

ALL_PROFILES = list(_all.values())
