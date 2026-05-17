import numpy as np

from router.board import Grid
from router.global_router import GlobalRouter
from router.netlist import Net, Pad


def _net(net_id, *xy_pairs):
    pads = [Pad(net_id=net_id, x=x, y=y, layer=0) for x, y in xy_pairs]
    return Net(net_id=net_id, name=f'N{net_id}', pads=pads)


def test_cost_map_shape_matches_grid():
    grid = Grid(30.0, 30.0, resolution=0.5)
    gr = GlobalRouter(grid, tile_size_mm=5.0)
    gr.plan_all([_net(1, (2, 2), (28, 28))])
    cost_map = gr.build_cost_map()
    assert cost_map.shape == (grid.num_layers, grid.rows, grid.cols)
    assert cost_map.dtype == np.float32


def test_uncongested_board_has_zero_cost_map():
    grid = Grid(30.0, 30.0, resolution=0.5)
    gr = GlobalRouter(grid, tile_size_mm=5.0)
    # capacity defaults to auto (~5 at this resolution); 2 nets won't exceed it
    gr.plan_all([_net(1, (2, 2), (28, 28)), _net(2, (2, 28), (28, 2))])
    cost_map = gr.build_cost_map()
    assert cost_map.max() == 0.0


def test_overcongested_tiles_get_positive_penalty():
    grid = Grid(20.0, 20.0, resolution=0.5)
    # Force capacity=1 so 4 nets through the same diagonal trigger a penalty
    gr = GlobalRouter(grid, tile_size_mm=5.0, capacity=1, penalty_per_excess=1.0)
    nets = [_net(i, (2, 2), (18, 18)) for i in range(1, 5)]
    gr.plan_all(nets)
    cost_map = gr.build_cost_map()
    assert cost_map.max() > 0.0


def test_plan_all_returns_all_nets_exactly_once():
    grid = Grid(20.0, 20.0, resolution=0.5)
    gr = GlobalRouter(grid, tile_size_mm=5.0)
    nets = [_net(i, (i * 3, 2), (i * 3, 18)) for i in range(1, 6)]
    ordered = gr.plan_all(nets)
    assert len(ordered) == len(nets)
    assert {n.net_id for n in ordered} == {n.net_id for n in nets}


def test_mm_to_tile_clamps_to_bounds():
    grid = Grid(20.0, 20.0, resolution=0.5)
    gr = GlobalRouter(grid, tile_size_mm=5.0)
    # Coordinates beyond the board should clamp to the last tile
    tc, tr = gr.mm_to_tile(999.0, 999.0)
    assert tc == gr.tile_cols - 1
    assert tr == gr.tile_rows - 1
    # Negative coordinates clamp to 0
    tc, tr = gr.mm_to_tile(-10.0, -10.0)
    assert tc == 0 and tr == 0
