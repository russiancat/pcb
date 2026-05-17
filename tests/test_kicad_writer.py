import os
import tempfile

from router.board import Grid
from router.manufacturer_profile import HOME_ETCH
from router.router import Router
from router.kicad_writer import KiCadWriter

_RULES = HOME_ETCH.design_rules

_MINIMAL_KICAD = """\
(kicad_pcb (version 20231120) (generator pcbnew)
  (net 0 "")
  (net 1 "N1")
)
"""


def _src(content=_MINIMAL_KICAD):
    f = tempfile.NamedTemporaryFile(
        mode='w', suffix='.kicad_pcb', delete=False, encoding='utf-8'
    )
    f.write(content)
    f.close()
    return f.name


def _writer(routed=None, vias=None, origin_x=0.0, origin_y=0.0):
    grid = Grid(10.0, 10.0, resolution=1.0)
    router = Router(grid, [], rules=_RULES)
    if routed is not None:
        router.routed = routed
    if vias is not None:
        router.vias = vias
    return KiCadWriter(grid, router, _RULES, origin_x, origin_y)


# ------------------------------------------------------------------
# File structure
# ------------------------------------------------------------------

def test_empty_router_writes_clean_file(tmp_path):
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        n_seg, n_via = _writer().write(src, out)
        assert n_seg == 0
        assert n_via == 0
        assert (tmp_path / "out.kicad_pcb").read_text().endswith(")\n")
    finally:
        os.unlink(src)


def test_output_has_balanced_parens(tmp_path):
    routed = {1: [[(2, 3, 0), (3, 3, 0), (4, 3, 0)]]}
    vias = {1: [(5, 3)]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(routed=routed, vias=vias).write(src, out)
        text = (tmp_path / "out.kicad_pcb").read_text()
        assert text.count("(") == text.count(")")
    finally:
        os.unlink(src)


def test_source_file_not_modified(tmp_path):
    src = _src()
    original = open(src).read()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(routed={1: [[(2, 3, 0), (3, 3, 0)]]}).write(src, out)
        assert open(src).read() == original
    finally:
        os.unlink(src)


# ------------------------------------------------------------------
# Segment generation
# ------------------------------------------------------------------

def test_segment_count_matches_cell_pairs(tmp_path):
    routed = {1: [[(2, 3, 0), (3, 3, 0), (4, 3, 0), (5, 3, 0)]]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        n_seg, _ = _writer(routed=routed).write(src, out)
        assert n_seg == 3
    finally:
        os.unlink(src)


def test_segment_content_correct(tmp_path):
    routed = {1: [[(2, 3, 0), (3, 3, 0)]]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(routed=routed).write(src, out)
        text = (tmp_path / "out.kicad_pcb").read_text()
        assert "(segment" in text
        assert '"F.Cu"' in text
        assert "(net 1)" in text
        assert "(start 2.000000 3.000000)" in text
        assert "(end 3.000000 3.000000)" in text
    finally:
        os.unlink(src)


def test_b_cu_layer_name(tmp_path):
    routed = {1: [[(2, 3, 1), (3, 3, 1)]]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(routed=routed).write(src, out)
        text = (tmp_path / "out.kicad_pcb").read_text()
        assert '"B.Cu"' in text
    finally:
        os.unlink(src)


def test_layer_switch_not_a_segment(tmp_path):
    routed = {1: [[(2, 3, 0), (2, 3, 1)]]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        n_seg, _ = _writer(routed=routed).write(src, out)
        assert n_seg == 0
    finally:
        os.unlink(src)


def test_origin_offset_applied_to_segment(tmp_path):
    routed = {1: [[(2, 3, 0), (3, 3, 0)]]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(routed=routed, origin_x=100.0, origin_y=50.0).write(src, out)
        text = (tmp_path / "out.kicad_pcb").read_text()
        # (2mm, 3mm) + (100, 50) → (102.000000, 53.000000)
        assert "102.000000" in text
        assert "53.000000" in text
    finally:
        os.unlink(src)


# ------------------------------------------------------------------
# Via generation
# ------------------------------------------------------------------

def test_via_count(tmp_path):
    vias = {1: [(3, 3)], 2: [(5, 5), (7, 7)]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _, n_via = _writer(vias=vias).write(src, out)
        assert n_via == 3
    finally:
        os.unlink(src)


def test_via_content_correct(tmp_path):
    vias = {1: [(3, 4)]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(vias=vias).write(src, out)
        text = (tmp_path / "out.kicad_pcb").read_text()
        assert "(via" in text
        assert '"F.Cu" "B.Cu"' in text
        assert "(net 1)" in text
        assert "(at 3.000000 4.000000)" in text
    finally:
        os.unlink(src)


def test_origin_offset_applied_to_via(tmp_path):
    vias = {1: [(3, 4)]}
    src = _src()
    out = str(tmp_path / "out.kicad_pcb")
    try:
        _writer(vias=vias, origin_x=10.0, origin_y=20.0).write(src, out)
        text = (tmp_path / "out.kicad_pcb").read_text()
        assert "(at 13.000000 24.000000)" in text
    finally:
        os.unlink(src)
