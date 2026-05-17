"""
Minimal KiCad S-expression parser.

Handles both KiCad 7/8 and KiCad 10 formats:
  - KiCad 7/8: pads reference nets as (net 1 "VCC"), top-level (net 1 "VCC") defs
  - KiCad 10:  pads reference nets as (net "VCC") by name only, no numeric defs

Does NOT import existing traces — we re-route from scratch.
"""

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .netlist import Component, Net, Pad


# ------------------------------------------------------------------
# S-expression tokeniser + parser
# ------------------------------------------------------------------

_TOKEN_RE = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


def _tokenize(text: str) -> List[str]:
    # Strip line comments
    text = re.sub(r'#[^\n]*', '', text)
    return _TOKEN_RE.findall(text)


def _parse_tokens(tokens: List[str], pos: int):
    """Recursive descent. Returns (tree_node, next_pos)."""
    tok = tokens[pos]
    if tok == '(':
        items = []
        pos += 1
        while pos < len(tokens) and tokens[pos] != ')':
            item, pos = _parse_tokens(tokens, pos)
            items.append(item)
        return items, pos + 1          # consume ')'
    if tok.startswith('"'):
        return tok[1:-1], pos + 1      # strip quotes
    try:
        return float(tok), pos + 1     # numeric atom
    except ValueError:
        return tok, pos + 1            # string atom


def parse_sexp(text: str):
    tokens = _tokenize(text)
    tree, _ = _parse_tokens(tokens, 0)
    return tree


# ------------------------------------------------------------------
# Tree helpers
# ------------------------------------------------------------------

def _find(node: list, key: str) -> Optional[list]:
    """First direct child list whose first element == key."""
    for item in node:
        if isinstance(item, list) and item and item[0] == key:
            return item
    return None


def _find_all(node: list, key: str) -> List[list]:
    return [item for item in node
            if isinstance(item, list) and item and item[0] == key]


def _at(node: list) -> Tuple[float, float, float]:
    """Extract (x, y, rotation_deg) from the first (at ...) child."""
    a = _find(node, 'at')
    if a is None:
        return 0.0, 0.0, 0.0
    x   = float(a[1]) if len(a) > 1 else 0.0
    y   = float(a[2]) if len(a) > 2 else 0.0
    rot = float(a[3]) if len(a) > 3 else 0.0
    return x, y, rot


def _rotate(x: float, y: float, deg: float) -> Tuple[float, float]:
    """Rotate (x, y) counter-clockwise by deg degrees (standard math)."""
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return x * c - y * s, x * s + y * c


# ------------------------------------------------------------------
# Board reader
# ------------------------------------------------------------------

@dataclass
class KiCadBoard:
    nets: Dict[int, str] = field(default_factory=dict)   # id → name
    components: List[Component] = field(default_factory=list)
    board_width: float = 100.0
    board_height: float = 80.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    # KiCad 10: net names assigned IDs on the fly
    _name_to_id: Dict[str, int] = field(default_factory=dict, repr=False)
    _next_id: int = field(default=1, repr=False)

    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str) -> 'KiCadBoard':
        with open(path, encoding='utf-8') as f:
            text = f.read()
        return cls.from_text(text)

    @classmethod
    def from_text(cls, text: str) -> 'KiCadBoard':
        board = cls()
        tree = parse_sexp(text)
        board._read_nets(tree)
        board._read_outline(tree)
        board._read_footprints(tree)
        return board

    # ------------------------------------------------------------------

    def _read_nets(self, tree: list) -> None:
        for item in tree:
            if isinstance(item, list) and item and item[0] == 'net':
                try:
                    self.nets[int(item[1])] = str(item[2]) if len(item) > 2 else ''
                except (ValueError, IndexError):
                    pass

    def _read_outline(self, tree: list) -> None:
        """Find board bounding box from Edge.Cuts layer elements."""
        xs, ys = [], []

        for item in tree:
            if not (isinstance(item, list) and item):
                continue
            if item[0] not in ('gr_rect', 'gr_line', 'gr_circle', 'gr_arc', 'gr_poly'):
                continue
            layer = _find(item, 'layer')
            if layer is None or 'Edge.Cuts' not in str(layer[1] if len(layer) > 1 else ''):
                continue
            for key in ('start', 'end', 'center', 'mid'):
                coord = _find(item, key)
                if coord and len(coord) >= 3:
                    xs.append(float(coord[1]))
                    ys.append(float(coord[2]))

        if xs and ys:
            self.origin_x = min(xs)
            self.origin_y = min(ys)
            self.board_width  = max(xs) - self.origin_x
            self.board_height = max(ys) - self.origin_y

    def _read_footprints(self, tree: list) -> None:
        for fp in _find_all(tree, 'footprint'):
            comp = self._read_footprint(fp)
            if comp is not None:
                self.components.append(comp)

    def _read_footprint(self, fp: list) -> Optional[Component]:
        # Reference designator: KiCad 7/8 uses (fp_text reference "U1" ...)
        # KiCad 10 uses (property "Reference" "U1" ...)
        ref = '?'
        for ft in _find_all(fp, 'fp_text'):
            if len(ft) > 2 and ft[1] == 'reference':
                ref = str(ft[2]); break
        if ref == '?':
            for prop in _find_all(fp, 'property'):
                if len(prop) > 2 and prop[1] == 'Reference':
                    ref = str(prop[2]); break

        fx, fy, frot = _at(fp)
        # Translate to board-relative origin
        fx -= self.origin_x
        fy -= self.origin_y

        pads: List[Pad] = []
        for pad_node in _find_all(fp, 'pad'):
            pad = self._read_pad(pad_node, fx, fy, frot)
            if pad is not None:
                pads.append(pad)

        if not pads:
            return None

        # Body = bounding box of pad centres + 1 mm margin
        margin = 1.0
        pad_xs = [p.x for p in pads]
        pad_ys = [p.y for p in pads]
        bx = min(pad_xs) - margin
        by = min(pad_ys) - margin
        bw = max(pad_xs) - min(pad_xs) + 2 * margin
        bh = max(pad_ys) - min(pad_ys) + 2 * margin

        return Component(ref=ref, x=bx, y=by, width=max(bw, 1.0), height=max(bh, 1.0), pads=pads)

    def _read_pad(self, pad_node: list, fx: float, fy: float,
                  frot: float) -> Optional[Pad]:
        net_node = _find(pad_node, 'net')
        if net_node is None or len(net_node) < 2:
            return None

        val = net_node[1]
        if isinstance(val, float):
            # KiCad 7/8: (net 1 "VCC")
            net_id = int(val)
            if net_id == 0:
                return None
        elif isinstance(val, str):
            # KiCad 10: (net "VCC") — assign IDs on the fly
            if not val:
                return None   # unconnected
            if val not in self._name_to_id:
                self._name_to_id[val] = self._next_id
                self.nets[self._next_id] = val
                self._next_id += 1
            net_id = self._name_to_id[val]
        else:
            return None

        at_node = _find(pad_node, 'at')
        if at_node is None:
            return None
        rx = float(at_node[1]) if len(at_node) > 1 else 0.0
        ry = float(at_node[2]) if len(at_node) > 2 else 0.0

        # Rotate pad offset by footprint rotation
        if frot:
            rx, ry = _rotate(rx, ry, -frot)   # KiCad CW → negate for std math

        ax = fx + rx
        ay = fy + ry

        # Layer: B.Cu only → layer 1; everything else (F.Cu, *.Cu) → layer 0
        layer = 0
        layers_node = _find(pad_node, 'layers')
        if layers_node:
            layer_names = [str(s) for s in layers_node[1:]]
            if all('B.Cu' in s for s in layer_names):
                layer = 1

        return Pad(net_id=net_id, x=ax, y=ay, layer=layer)

    # ------------------------------------------------------------------

    def build_nets_and_components(self) -> Tuple[List[Net], List[Component]]:
        """Aggregate pads by net_id and return (nets, components)."""
        net_pads: Dict[int, List[Pad]] = defaultdict(list)
        for comp in self.components:
            for pad in comp.pads:
                net_pads[pad.net_id].append(pad)

        nets = [
            Net(net_id=nid,
                name=self.nets.get(nid, f'net{nid}'),
                pads=pads)
            for nid, pads in sorted(net_pads.items())
        ]
        return nets, self.components
