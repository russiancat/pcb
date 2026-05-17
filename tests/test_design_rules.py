from router.design_rules import (
    HOME_ETCH, LOCAL_FAB_BASIC, LOCAL_FAB_MODERN,
    HOBBYIST_ONLINE, PROFESSIONAL, ZBOTIC_2L, ZBOTIC_4L,
)

ALL_PRESETS = [
    HOME_ETCH, LOCAL_FAB_BASIC, LOCAL_FAB_MODERN,
    HOBBYIST_ONLINE, PROFESSIONAL, ZBOTIC_2L, ZBOTIC_4L,
]


def test_all_presets_have_positive_values():
    for p in ALL_PRESETS:
        assert p.resolution_mm > 0,         f"{p.name}: resolution_mm <= 0"
        assert p.clearance_mm > 0,           f"{p.name}: clearance_mm <= 0"
        assert p.via_drill_mm > 0,           f"{p.name}: via_drill_mm <= 0"
        assert p.via_annular_mm > 0,         f"{p.name}: via_annular_mm <= 0"
        assert p.via_cost > 0,               f"{p.name}: via_cost <= 0"
        assert p.edge_clearance_mm > 0,      f"{p.name}: edge_clearance_mm <= 0"


def test_clearance_cells_is_at_least_one():
    for p in ALL_PRESETS:
        assert p.clearance_cells >= 1, f"{p.name}: clearance_cells < 1"


def test_home_etch_has_highest_via_cost():
    for p in ALL_PRESETS:
        assert HOME_ETCH.via_cost >= p.via_cost, \
            f"HOME_ETCH via_cost should be >= {p.name}"


def test_resolution_coarser_to_finer():
    # Presets should go from coarser to finer in this order
    ordered = [HOME_ETCH, LOCAL_FAB_BASIC, LOCAL_FAB_MODERN,
               HOBBYIST_ONLINE, PROFESSIONAL]
    for a, b in zip(ordered, ordered[1:]):
        assert a.resolution_mm >= b.resolution_mm, \
            f"{a.name} should be coarser than {b.name}"


def test_zbotic_specs_match_documentation():
    # From zbotic.in/pcb-technical-design-guidelines/
    assert abs(ZBOTIC_2L.resolution_mm - 0.127) < 0.001
    assert abs(ZBOTIC_2L.clearance_mm  - 0.127) < 0.001
    assert abs(ZBOTIC_4L.resolution_mm - 0.1)   < 0.001
    assert abs(ZBOTIC_4L.clearance_mm  - 0.1)   < 0.001
