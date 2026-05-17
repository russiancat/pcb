"""Tests for the DesignRules dataclass (properties and behaviour, not presets).
Manufacturer presets are tested in test_manufacturer_profile.py.
"""

from router.design_rules import DesignRules


def _rules(resolution, clearance):
    return DesignRules(
        name="test", resolution_mm=resolution, clearance_mm=clearance,
        component_clearance_mm=clearance, via_drill_mm=0.3,
        via_annular_mm=0.1, via_cost=4.0, edge_clearance_mm=0.3,
    )


def test_clearance_cells_rounds_correctly():
    r = _rules(resolution=0.25, clearance=0.25)
    assert r.clearance_cells == 1


def test_clearance_cells_minimum_is_one():
    # clearance < resolution → still returns 1
    r = _rules(resolution=1.0, clearance=0.1)
    assert r.clearance_cells == 1


def test_clearance_cells_two_when_double_resolution():
    r = _rules(resolution=0.127, clearance=0.254)
    assert r.clearance_cells == 2


def test_component_clearance_cells():
    r = DesignRules(
        name="t", resolution_mm=0.5, clearance_mm=0.5,
        component_clearance_mm=1.0, via_drill_mm=0.3,
        via_annular_mm=0.1, via_cost=4.0, edge_clearance_mm=0.3,
    )
    assert r.component_clearance_cells == 2


def test_summary_contains_name():
    r = _rules(0.127, 0.127)
    assert "test" in r.summary()


def test_frozen_dataclass_rejects_mutation():
    import pytest
    r = _rules(0.127, 0.127)
    with pytest.raises((AttributeError, TypeError)):
        r.resolution_mm = 0.5  # type: ignore
