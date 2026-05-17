from router.board import Grid, EMPTY, OBSTACLE


def make_grid(w=10.0, h=10.0, res=1.0, layers=2):
    return Grid(w, h, resolution=res, num_layers=layers)


def test_grid_dimensions():
    g = make_grid(10.0, 10.0, 1.0)
    assert g.cols == 11   # int(10/1)+1 = 11
    assert g.rows == 11
    assert g.num_layers == 2
    assert g.grid.shape == (2, 11, 11)


def test_mm_to_grid_roundtrip():
    g = make_grid(10.0, 10.0, 0.5)
    col, row = g.mm_to_grid(3.0, 4.5)
    x, y = g.grid_to_mm(col, row)
    assert abs(x - 3.0) < 1e-9
    assert abs(y - 4.5) < 1e-9


def test_mark_pad_occupies_correct_cell():
    g = make_grid()
    g.mark_pad(3.0, 4.0, layer=0, net_id=7)
    col, row = g.mm_to_grid(3.0, 4.0)
    assert g.grid[0, row, col] == 7


def test_same_net_passable_through_own_pad():
    g = make_grid()
    g.mark_pad(5.0, 5.0, layer=0, net_id=1)
    col, row = g.mm_to_grid(5.0, 5.0)
    assert g.is_passable(col, row, 0, net_id=1, clearance_cells=0)


def test_foreign_net_blocked_by_pad():
    g = make_grid()
    g.mark_pad(5.0, 5.0, layer=0, net_id=1)
    col, row = g.mm_to_grid(5.0, 5.0)
    assert not g.is_passable(col, row, 0, net_id=2, clearance_cells=0)


def test_clearance_blocks_adjacent_cell():
    g = make_grid()
    g.mark_pad(5.0, 5.0, layer=0, net_id=1)
    col, row = g.mm_to_grid(5.0, 5.0)
    # 1 cell away should be blocked for a foreign net with clearance=1
    assert not g.is_passable(col + 1, row, 0, net_id=2, clearance_cells=1)
    # 2 cells away is fine
    assert g.is_passable(col + 2, row, 0, net_id=2, clearance_cells=1)


def test_edge_keepout_marks_border_as_obstacle():
    g = make_grid()
    g.mark_edge_keepout(1)
    assert g.grid[0, 0, 0] == OBSTACLE
    assert g.grid[0, 0, 5] == OBSTACLE
    # Interior should be untouched
    assert g.grid[0, 2, 2] == EMPTY


def test_pad_overrides_keepout():
    # A pad placed in the keepout zone must remain reachable (pads override obstacles).
    g = make_grid()
    g.mark_edge_keepout(2)
    g.mark_pad(0.0, 0.0, layer=0, net_id=5)
    col, row = g.mm_to_grid(0.0, 0.0)
    assert g.grid[0, row, col] == 5


def test_clear_net_removes_traces_but_keeps_pads():
    g = make_grid()
    g.mark_pad(3.0, 3.0, layer=0, net_id=7)
    g.mark_trace(4, 3, 0, 7)
    g.mark_trace(5, 3, 0, 7)
    g.clear_net(7)
    # Traces cleared
    assert g.grid[0, 3, 4] == EMPTY
    assert g.grid[0, 3, 5] == EMPTY
    # Pad survives
    col, row = g.mm_to_grid(3.0, 3.0)
    assert g.grid[0, row, col] == 7
