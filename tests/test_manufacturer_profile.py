from router.design_rules import DesignRules
from router.drc import ViolationType, check_profile_compatibility
from router.manufacturer_profile import (
    ALL_PROFILES, HOME_ETCH, JLCPCB_2L, JLCPCB_4L,
    PCBWAY_2L, PCBWAY_4L, ZBOTIC_2L, ZBOTIC_4L,
    ManufacturerProfile, load_all_profiles, get_profile,
)


# ------------------------------------------------------------------
# Loader
# ------------------------------------------------------------------

def test_load_all_returns_all_seven():
    profiles = load_all_profiles()
    assert len(profiles) == 7


def test_get_profile_by_key():
    p = get_profile("pcbway_2l")
    assert p.name == PCBWAY_2L.name


def test_get_profile_unknown_key_raises():
    import pytest
    with pytest.raises(KeyError, match="unknown_fab"):
        get_profile("unknown_fab")


def test_all_profiles_constant_matches_loader():
    assert len(ALL_PROFILES) == 7


# ------------------------------------------------------------------
# Profile sanity checks
# ------------------------------------------------------------------

def test_all_profiles_have_positive_values():
    for p in ALL_PROFILES:
        dr = p.design_rules
        assert dr.resolution_mm > 0,       f"{p.name}: resolution_mm <= 0"
        assert dr.clearance_mm > 0,         f"{p.name}: clearance_mm <= 0"
        assert dr.via_drill_mm > 0,         f"{p.name}: via_drill_mm <= 0"
        assert dr.via_annular_mm > 0,       f"{p.name}: via_annular_mm <= 0"
        assert p.min_via_diameter_mm > 0,   f"{p.name}: min_via_diameter_mm <= 0"
        assert p.min_pth_drill_mm > 0,      f"{p.name}: min_pth_drill_mm <= 0"
        assert p.max_pth_drill_mm > 0,      f"{p.name}: max_pth_drill_mm <= 0"
        assert p.min_npth_drill_mm > 0,     f"{p.name}: min_npth_drill_mm <= 0"
        assert p.min_hole_to_hole_mm > 0,   f"{p.name}: min_hole_to_hole_mm <= 0"
        assert p.min_silk_text_height_mm > 0
        assert p.min_silk_clearance_mm > 0


def test_via_diameter_consistent_with_drill_and_annular():
    for p in ALL_PROFILES:
        dr = p.design_rules
        computed = dr.via_drill_mm + 2 * dr.via_annular_mm
        assert abs(computed - p.min_via_diameter_mm) < 0.001, (
            f"{p.name}: via_diameter {p.min_via_diameter_mm:.3f} != "
            f"drill+2×annular {computed:.3f}"
        )


def test_4l_profiles_finer_than_2l():
    assert PCBWAY_4L.design_rules.resolution_mm < PCBWAY_2L.design_rules.resolution_mm
    assert JLCPCB_4L.design_rules.resolution_mm < JLCPCB_2L.design_rules.resolution_mm
    assert ZBOTIC_4L.design_rules.resolution_mm < ZBOTIC_2L.design_rules.resolution_mm


def test_jlcpcb_silk_stricter_than_pcbway():
    assert JLCPCB_2L.min_silk_text_height_mm > PCBWAY_2L.min_silk_text_height_mm


def test_home_etch_has_highest_via_cost():
    for p in ALL_PROFILES:
        assert HOME_ETCH.design_rules.via_cost >= p.design_rules.via_cost, \
            f"HOME_ETCH via_cost should be >= {p.name}"


# ------------------------------------------------------------------
# merge() — strictest-wins
# ------------------------------------------------------------------

def _make_profile(name, res, via_drill, via_annular, via_diam,
                  silk_h=0.8, pth_max=6.3):
    dr = DesignRules(
        name=name, resolution_mm=res, clearance_mm=res,
        component_clearance_mm=0.2, via_drill_mm=via_drill,
        via_annular_mm=via_annular, via_cost=4.0, edge_clearance_mm=0.3,
    )
    return ManufacturerProfile(
        name=name, source_url="", design_rules=dr,
        min_via_diameter_mm=via_diam,
        min_pth_drill_mm=0.2, max_pth_drill_mm=pth_max,
        min_npth_drill_mm=0.5, min_hole_to_hole_mm=0.5,
        min_silk_text_height_mm=silk_h, min_silk_clearance_mm=0.15,
    )


def test_merge_takes_max_of_minimums():
    a = _make_profile("A", res=0.127, via_drill=0.3, via_annular=0.1, via_diam=0.5)
    b = _make_profile("B", res=0.2,   via_drill=0.2, via_annular=0.15, via_diam=0.5)
    merged = ManufacturerProfile.merge(a, b)
    assert merged.design_rules.resolution_mm == 0.2
    assert merged.design_rules.via_drill_mm == 0.3
    assert merged.design_rules.via_annular_mm == 0.15


def test_merge_takes_min_of_maximums():
    a = _make_profile("A", res=0.127, via_drill=0.3, via_annular=0.1,
                      via_diam=0.5, pth_max=6.35)
    b = _make_profile("B", res=0.127, via_drill=0.3, via_annular=0.1,
                      via_diam=0.5, pth_max=3.0)
    merged = ManufacturerProfile.merge(a, b)
    assert merged.max_pth_drill_mm == 3.0


def test_merge_single_profile_returns_itself():
    assert ManufacturerProfile.merge(PCBWAY_2L) is PCBWAY_2L


def test_merge_silk_strictest_wins():
    a = _make_profile("A", res=0.127, via_drill=0.3, via_annular=0.1,
                      via_diam=0.5, silk_h=0.8)
    b = _make_profile("B", res=0.127, via_drill=0.3, via_annular=0.1,
                      via_diam=0.5, silk_h=1.0)
    assert ManufacturerProfile.merge(a, b).min_silk_text_height_mm == 1.0


# ------------------------------------------------------------------
# check_profile_compatibility
# ------------------------------------------------------------------

def test_home_etch_compatible_with_pcbway():
    # HOME_ETCH routes at 1mm — well above PCBWay's 0.127mm minimum
    assert check_profile_compatibility(HOME_ETCH.design_rules, PCBWAY_2L) == []


def test_too_narrow_trace_flagged():
    fine = DesignRules(
        name="too fine", resolution_mm=0.05, clearance_mm=0.05,
        component_clearance_mm=0.1, via_drill_mm=0.3,
        via_annular_mm=0.1, via_cost=4.0, edge_clearance_mm=0.3,
    )
    types = {v.type for v in check_profile_compatibility(fine, PCBWAY_2L)}
    assert ViolationType.TRACE_TOO_NARROW in types


def test_too_small_via_drill_flagged():
    bad = DesignRules(
        name="bad via", resolution_mm=0.127, clearance_mm=0.127,
        component_clearance_mm=0.2, via_drill_mm=0.1,
        via_annular_mm=0.1, via_cost=4.0, edge_clearance_mm=0.3,
    )
    types = {v.type for v in check_profile_compatibility(bad, PCBWAY_2L)}
    assert ViolationType.VIA_DRILL_TOO_SMALL in types


def test_pcbway_2l_rules_self_compatible():
    assert check_profile_compatibility(PCBWAY_2L.design_rules, PCBWAY_2L) == []
