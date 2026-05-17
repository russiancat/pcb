from router.board import Grid, EMPTY
from router.design_rules import HOME_ETCH
from router.netlist import Net, Pad
from router.router import Router, _mst_pad_order


def _pad(x, y, net_id, layer=0):
    return Pad(net_id=net_id, x=x, y=y, layer=layer)


def _net(net_id, *xy_pairs, layer=0):
    return Net(net_id=net_id, name=f'N{net_id}',
               pads=[_pad(x, y, net_id, layer) for x, y in xy_pairs])


# ------------------------------------------------------------------
# MST ordering
# ------------------------------------------------------------------

def test_mst_order_two_pads_returns_both():
    pads = [_pad(0, 0, 1), _pad(5, 0, 1)]
    order = _mst_pad_order(pads)
    assert sorted(order) == [0, 1]


def test_mst_order_picks_closest_pair_first():
    # Pads: A(0,0), B(100,0), C(1,0) — closest pair is A(idx=0) and C(idx=2)
    pads = [_pad(0, 0, 1), _pad(100, 0, 1), _pad(1, 0, 1)]
    order = _mst_pad_order(pads)
    assert set(order[:2]) == {0, 2}


def test_mst_order_covers_all_pads():
    pads = [_pad(i * 3, 0, 1) for i in range(5)]
    order = _mst_pad_order(pads)
    assert sorted(order) == list(range(5))


# ------------------------------------------------------------------
# route_all on a simple synthetic board
# ------------------------------------------------------------------

def _build_simple_board():
    """Two non-crossing 2-pad nets on a 10×10mm board at 1mm resolution."""
    rules = HOME_ETCH   # 1mm trace, 1mm clearance — coarse but deterministic
    grid = Grid(10.0, 10.0, resolution=1.0)
    grid.mark_edge_keepout(1)
    nets = [
        _net(1, (2.0, 3.0), (8.0, 3.0)),
        _net(2, (2.0, 7.0), (8.0, 7.0)),
    ]
    for net in nets:
        for pad in net.pads:
            grid.mark_pad(pad.x, pad.y, pad.layer, pad.net_id)
    return grid, nets, rules


def test_route_all_completes_simple_board():
    grid, nets, rules = _build_simple_board()
    router = Router(grid, nets, rules=rules, max_iterations=2, verbose=False)
    failed = router.route_all()
    assert failed == []
    assert len(router.routed) == 2


def test_routed_cells_belong_to_correct_net():
    grid, nets, rules = _build_simple_board()
    router = Router(grid, nets, rules=rules, max_iterations=2, verbose=False)
    router.route_all()
    # Every cell in each route must carry the right net_id
    for net in nets:
        for path in router.routed.get(net.net_id, []):
            for col, row, layer in path:
                assert grid.grid[layer, row, col] == net.net_id


def test_no_short_circuits_after_routing():
    """Adjacent cells must never belong to two different nets."""
    import numpy as np
    grid, nets, rules = _build_simple_board()
    router = Router(grid, nets, rules=rules, max_iterations=2, verbose=False)
    router.route_all()
    g = grid.grid
    for layer in range(grid.num_layers):
        lg = g[layer]
        # Horizontal adjacency
        left, right = lg[:, :-1], lg[:, 1:]
        conflict = (left > 0) & (right > 0) & (left != right)
        assert not conflict.any(), "Short circuit found in horizontal scan"
        # Vertical adjacency
        top, bot = lg[:-1, :], lg[1:, :]
        conflict = (top > 0) & (bot > 0) & (top != bot)
        assert not conflict.any(), "Short circuit found in vertical scan"


# ------------------------------------------------------------------
# Copper pour
# ------------------------------------------------------------------

def test_copper_pour_fills_empty_cells():
    grid = Grid(10.0, 10.0, resolution=1.0)
    grid.mark_pad(5.0, 5.0, layer=0, net_id=99)
    router = Router(grid, [], rules=HOME_ETCH, verbose=False)
    filled = router.copper_pour(net_id=99, layer=0)
    assert filled > 0
    assert 99 in router.pour_masks
    assert router.pour_masks[99][0].any()


def test_copper_pour_does_not_overwrite_foreign_net():
    grid = Grid(10.0, 10.0, resolution=1.0)
    grid.mark_pad(5.0, 5.0, layer=0, net_id=1)    # GND seed
    grid.mark_trace(7, 5, 0, 2)                    # foreign trace
    router = Router(grid, [], rules=HOME_ETCH, verbose=False)
    router.copper_pour(net_id=1, layer=0)
    assert grid.grid[0, 5, 7] == 2                 # foreign net untouched


def test_copper_pour_no_seed_returns_zero():
    grid = Grid(10.0, 10.0, resolution=1.0)
    router = Router(grid, [], rules=HOME_ETCH, verbose=False)
    # net_id 42 has no pads — nothing to seed the pour from
    filled = router.copper_pour(net_id=42, layer=0)
    assert filled == 0
