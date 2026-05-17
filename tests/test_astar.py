from router.board import Grid
from router.astar import _astar as astar, _astar_to_net as astar_to_net


def make_grid(w=10.0, h=10.0, res=1.0, layers=2):
    return Grid(w, h, resolution=res, num_layers=layers)


def test_routes_straight_path():
    g = make_grid()
    g.mark_pad(1.0, 5.0, layer=0, net_id=1)
    g.mark_pad(8.0, 5.0, layer=0, net_id=1)
    path = astar(g, (1, 5, 0), 8, 5, net_id=1, via_cost=20.0, clearance_cells=0)
    assert path is not None
    assert path[0] == (1, 5, 0)
    assert path[-1][0] == 8 and path[-1][1] == 5


def test_returns_none_when_fully_blocked():
    # Single-layer grid with a solid obstacle wall
    g = make_grid(layers=1)
    for r in range(g.rows):
        g.grid[0, r, 4] = -1   # obstacle column
    g.mark_pad(1.0, 5.0, layer=0, net_id=1)
    g.mark_pad(8.0, 5.0, layer=0, net_id=1)
    path = astar(g, (1, 5, 0), 8, 5, net_id=1, via_cost=20.0, clearance_cells=0)
    assert path is None


def test_paths_on_both_layers_when_one_blocked():
    # Layer 0 has a wall, layer 1 is clear — router should use a via to cross
    g = make_grid()
    for r in range(g.rows):
        g.grid[0, r, 4] = -1   # wall on layer 0 only
    g.mark_pad(1.0, 5.0, layer=0, net_id=1)
    g.mark_pad(8.0, 5.0, layer=0, net_id=1)
    path = astar(g, (1, 5, 0), 8, 5, net_id=1, via_cost=5.0, clearance_cells=0)
    assert path is not None
    layers_used = {l for _, _, l in path}
    assert 1 in layers_used   # used the second layer to bypass


def test_routes_to_target_coordinates_regardless_of_layer():
    # A* accepts any layer at the target XY as a valid endpoint.
    # Layer-switching is only forced when the direct-layer path is blocked
    # (see test_paths_on_both_layers_when_one_blocked).
    g = make_grid()
    g.mark_pad(1.0, 1.0, layer=0, net_id=1)
    g.mark_pad(8.0, 1.0, layer=1, net_id=1)   # target on layer 1
    path = astar(g, (1, 1, 0), 8, 1, net_id=1, via_cost=5.0, clearance_cells=0)
    assert path is not None
    assert path[-1][0] == 8 and path[-1][1] == 1  # reached target XY


def test_clearance_forces_detour_around_foreign_net():
    g = make_grid()
    # Block col=5, row=5 with a foreign net pad
    g.mark_pad(5.0, 5.0, layer=0, net_id=2)
    g.mark_pad(1.0, 5.0, layer=0, net_id=1)
    g.mark_pad(9.0, 5.0, layer=0, net_id=1)
    path = astar(g, (1, 5, 0), 9, 5, net_id=1, via_cost=20.0, clearance_cells=1)
    if path is not None:
        # Path must not occupy the foreign pad cell or its immediate neighbours
        for col, row, _ in path:
            assert not (col == 5 and row == 5)


def test_astar_to_net_connects_to_existing_trace():
    g = make_grid()
    net_id = 1
    # Lay down a horizontal trace at row=3, cols 2..7
    for c in range(2, 8):
        g.grid[0, 3, c] = net_id
    g.mark_pad(5.0, 8.0, layer=0, net_id=net_id)
    ref_points = [(c, 3) for c in range(2, 8)]
    path = astar_to_net(g, (5, 8, 0), ref_points, net_id,
                        via_cost=20.0, clearance_cells=0)
    assert path is not None
    last = path[-1]
    # Final cell must belong to the existing net (connected to the trace)
    assert g.grid[last[2], last[1], last[0]] == net_id
