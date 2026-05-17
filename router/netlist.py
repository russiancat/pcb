from dataclasses import dataclass, field
from typing import List


@dataclass
class Pad:
    net_id: int
    x: float        # mm
    y: float        # mm
    layer: int = 0  # 0 = top copper, 1 = bottom copper


@dataclass
class Net:
    net_id: int
    name: str
    pads: List[Pad] = field(default_factory=list)

    def estimated_wirelength(self) -> float:
        """Sum of Manhattan distances between consecutive pads."""
        total = 0.0
        for i in range(1, len(self.pads)):
            total += abs(self.pads[i].x - self.pads[i - 1].x)
            total += abs(self.pads[i].y - self.pads[i - 1].y)
        return total


@dataclass
class Component:
    ref: str
    x: float        # mm, body origin
    y: float        # mm, body origin
    width: float    # mm
    height: float   # mm
    pads: List[Pad] = field(default_factory=list)
