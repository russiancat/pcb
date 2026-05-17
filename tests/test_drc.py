from router.board import Grid
from router.drc import DRCViolation, ViolationType, run_drc
from router.manufacturer_profile import HOME_ETCH
from router.netlist import Net, Pad
from router.router import Router

_RULES = HOME_ETCH.design_rules


def _net(net_id, *xy_pairs, layer=0):
    pads = [Pad(net_id=net_id, x=x, y=y, layer=layer) for x, y in xy_pairs]
    return Net(net_id=net_id, name=f'N{net_id}', pads=pads)


def _routed_board():
    """Two routed 2-pad nets with clearance, no violations."""
    grid = Grid(10.0, 10.0, resolution=1.0)
    grid.mark_edge_keepout(1)
    nets = [_net(1, (2.0, 3.0), (8.0, 3.0)), _net(2, (2.0, 7.0), (8.0, 7.0))]
    for net in nets:
        for pad in net.pads:
            grid.mark_pad(pad.x, pad.y, pad.layer, pad.net_id)
    router = Router(grid, nets, rules=_RULES, max_iterations=2)
    router.route_all()
    return grid, nets, router


def test_no_violations_on_clean_board():
    grid, nets, router = _routed_board()
    violations = run_drc(grid, nets, router, _RULES)
    shorts = [v for v in violations if v.type == ViolationType.SHORT_CIRCUIT]
    assert shorts == [], f"Unexpected short circuits: {shorts}"


def test_open_net_reported():
    grid = Grid(10.0, 10.0, resolution=1.0)
    nets = [_net(1, (2.0, 3.0), (8.0, 3.0))]
    grid.mark_pad(2.0, 3.0, layer=0, net_id=1)
    grid.mark_pad(8.0, 3.0, layer=0, net_id=1)
    router = Router(grid, nets, rules=_RULES)
    violations = run_drc(grid, nets, router, _RULES)
    opens = [v for v in violations if v.type == ViolationType.OPEN]
    assert len(opens) == 1
    assert "N1" in opens[0].description


def test_short_circuit_detected():
    grid = Grid(10.0, 10.0, resolution=1.0)
    nets = [_net(1, (2.0, 5.0), (8.0, 5.0)), _net(2, (3.0, 5.0), (9.0, 5.0))]
    for net in nets:
        for pad in net.pads:
            grid.mark_pad(pad.x, pad.y, pad.layer, pad.net_id)
    router = Router(grid, nets, rules=_RULES)
    # Manually plant adjacent traces of different nets (no clearance check)
    grid.grid[0, 5, 5] = 1
    grid.grid[0, 5, 6] = 2
    router.routed[1] = [[(2, 5, 0), (5, 5, 0)]]
    router.routed[2] = [[(3, 5, 0), (6, 5, 0)]]
    violations = run_drc(grid, nets, router, _RULES)
    shorts = [v for v in violations if v.type == ViolationType.SHORT_CIRCUIT]
    assert len(shorts) >= 1


def test_violation_str_includes_type_name():
    v = DRCViolation(ViolationType.OPEN, "net X unconnected")
    assert str(v) == "OPEN: net X unconnected"


def test_is_pad_cell():
    grid = Grid(10.0, 10.0, resolution=1.0)
    grid.mark_pad(5.0, 5.0, layer=0, net_id=1)
    col, row = grid.mm_to_grid(5.0, 5.0)
    assert grid.is_pad_cell(0, row, col) is True
    assert grid.is_pad_cell(0, row, col + 1) is False
    assert grid.is_pad_cell(1, row, col) is False  # pad is only on layer 0
