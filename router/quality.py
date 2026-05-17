from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class QualityReport:
    matched_nets: int
    wire_overhead_pct: float
    worse_nets: Tuple[Tuple[str, float, float, float], ...]
    better_nets_count: int
    via_ratio: Optional[float]
    quality_index: float


def quality_report(
    our_wire_by_name: Dict[str, float],
    our_pct: float,
    our_vias: int,
    ref_wire_by_name: Dict[str, float],
    ref_vias: int,
) -> Optional[QualityReport]:
    common = set(our_wire_by_name.keys()) & set(ref_wire_by_name.keys())
    if not common:
        return None

    ref_common = sum(ref_wire_by_name[n] for n in common)
    our_common = sum(our_wire_by_name[n] for n in common)
    wire_overhead_pct = (our_common - ref_common) / ref_common * 100 if ref_common else 0.0

    worse_nets = tuple(sorted(
        [
            (n, our_wire_by_name[n], ref_wire_by_name[n],
             100 * (our_wire_by_name[n] - ref_wire_by_name[n]) / ref_wire_by_name[n])
            for n in common
            if our_wire_by_name[n] > ref_wire_by_name[n] * 1.5
        ],
        key=lambda x: -x[3],
    )[:5])

    better_nets_count = sum(1 for n in common if our_wire_by_name[n] < ref_wire_by_name[n] * 0.9)
    via_ratio = our_vias / ref_vias if ref_vias else None

    comp_score = our_pct / 100.0
    wire_score = min(1.0, ref_common / our_common) if our_common else 0.0
    via_score = min(1.0, ref_vias / our_vias) if our_vias and ref_vias else 1.0
    quality_index = round(
        100 * comp_score * (0.5 * wire_score + 0.3) * (0.2 * via_score + 0.8), 1
    )

    return QualityReport(
        matched_nets=len(common),
        wire_overhead_pct=wire_overhead_pct,
        worse_nets=worse_nets,
        better_nets_count=better_nets_count,
        via_ratio=via_ratio,
        quality_index=quality_index,
    )
