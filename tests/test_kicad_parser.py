from pathlib import Path

from router.kicad_parser import KiCadBoard, parse_sexp

DATA_DIR = Path(__file__).parent.parent / 'data'

# ------------------------------------------------------------------
# Minimal inline boards for format-specific tests
# ------------------------------------------------------------------

_V8 = """
(kicad_pcb
  (net 0 "")
  (net 1 "VCC")
  (net 2 "GND")
  (footprint "R"
    (at 10 10)
    (fp_text reference "R1" (at 0 0))
    (pad "1" smd (at -1 0) (layers "F.Cu") (net 1 "VCC"))
    (pad "2" smd (at  1 0) (layers "F.Cu") (net 2 "GND"))
  )
  (footprint "R"
    (at 20 10)
    (fp_text reference "R2" (at 0 0))
    (pad "1" smd (at -1 0) (layers "F.Cu") (net 1 "VCC"))
    (pad "2" smd (at  1 0) (layers "F.Cu") (net 2 "GND"))
  )
  (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts"))
)
"""

_V10 = """
(kicad_pcb
  (footprint "R"
    (at 10 10)
    (property "Reference" "R1")
    (pad "1" smd (at -1 0) (layers "F.Cu") (net "VCC"))
    (pad "2" smd (at  1 0) (layers "F.Cu") (net "GND"))
  )
  (footprint "R"
    (at 20 10)
    (property "Reference" "R2")
    (pad "1" smd (at -1 0) (layers "F.Cu") (net "VCC"))
    (pad "2" smd (at  1 0) (layers "F.Cu") (net "GND"))
  )
  (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts"))
)
"""

# ------------------------------------------------------------------
# S-expression parser
# ------------------------------------------------------------------

def test_parse_sexp_atoms():
    tree = parse_sexp('(foo 1 "bar" (baz 2.5))')
    assert tree[0] == 'foo'
    assert tree[1] == 1.0
    assert tree[2] == 'bar'
    assert tree[3] == ['baz', 2.5]


def test_parse_sexp_nested():
    tree = parse_sexp('(a (b (c 3)))')
    assert tree[0] == 'a'
    assert tree[1][0] == 'b'
    assert tree[1][1][0] == 'c'
    assert tree[1][1][1] == 3.0


# ------------------------------------------------------------------
# KiCad 7/8 format (numeric net IDs)
# ------------------------------------------------------------------

def test_v8_net_table_parsed():
    board = KiCadBoard.from_text(_V8)
    assert board.nets[1] == 'VCC'
    assert board.nets[2] == 'GND'


def test_v8_two_components_two_nets():
    board = KiCadBoard.from_text(_V8)
    nets, comps = board.build_nets_and_components()
    assert len(comps) == 2
    assert {n.name for n in nets} == {'VCC', 'GND'}
    # Each net has 2 pads (one per component)
    for net in nets:
        assert len(net.pads) == 2


# ------------------------------------------------------------------
# KiCad 10 format (name-only net references)
# ------------------------------------------------------------------

def test_v10_net_names_assigned_ids():
    board = KiCadBoard.from_text(_V10)
    nets, comps = board.build_nets_and_components()
    assert len(comps) == 2
    assert {n.name for n in nets} == {'VCC', 'GND'}


# ------------------------------------------------------------------
# Board outline
# ------------------------------------------------------------------

def test_board_outline_from_gr_rect():
    board = KiCadBoard.from_text(_V8)
    assert abs(board.board_width  - 30.0) < 0.5
    assert abs(board.board_height - 20.0) < 0.5


# ------------------------------------------------------------------
# Real file
# ------------------------------------------------------------------

def test_parse_real_test_board():
    path = DATA_DIR / 'test_board.kicad_pcb'
    board = KiCadBoard.from_file(str(path))
    nets, comps = board.build_nets_and_components()
    assert len(nets) > 0
    assert len(comps) > 0
    assert board.board_width > 0
    assert board.board_height > 0
