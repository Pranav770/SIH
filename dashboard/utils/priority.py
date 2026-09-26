"""Explainable rescue-priority engine (Step 10).

Rule-based scoring — explicitly *not* an opaque model.  Each survivor gets
a P1–P4 label **plus the human-readable reasons that produced it**, so an
operator (or judge) can see exactly why a survivor was prioritised.

Score components (max 100):

===========================  ======  ===================================
component                    points  rationale
===========================  ======  ===================================
survivor detected             40     a detected survivor is always
                                     actionable
confidence                    25     25 × detector confidence
nearby hazard severity      0–15     CRITICAL 15 / HIGH 12 / MEDIUM 6 /
                                     LOW 3, halved beyond 60 m
hazard-zone exposure        0–10     inside (≤25 m) +10, adjacent +5
accessibility (drone dist.)  0–10     ≤100 m +10, ≤250 m +6, else +2
===========================  ======  ===================================

Bands: ≥78 → P1 · ≥62 → P2 · ≥46 → P3 · else → P4
"""

from __future__ import annotations

from dataclasses import dataclass

from models.detection import Severity
from models.hazard import Hazard
from models.survivor import Survivor

P1_MIN, P2_MIN, P3_MIN = 78.0, 62.0, 46.0

_SEV_HAZARD_POINTS = {
    Severity.CRITICAL: 15,
    Severity.HIGH: 12,
    Severity.MEDIUM: 6,
    Severity.LOW: 3,
}


@dataclass
class PriorityResult:
    label: str
    score: float
    reasons: list[str]


def _grid_dist_m(a_x: int, a_y: int, b_x: int, b_y: int,
                 cell_size_m: float) -> float:
    return ((a_x - b_x) ** 2 + (a_y - b_y) ** 2) ** 0.5 * cell_size_m


def assess_survivor_priority(
    survivor: Survivor,
    hazards: list[Hazard],
    drone_pos: tuple[int, int],
    cell_size_m: float = 10.0,
) -> PriorityResult:
    reasons: list[str] = ["Survivor detected"]
    score = 40.0

    conf = max(0.0, min(1.0, float(survivor.confidence or 0.0)))
    score += 25.0 * conf
    if conf >= 0.8:
        reasons.append(f"High confidence {conf:.1%}")

    # --- nearby hazard ---------------------------------------------------
    nearest_h: Hazard | None = None
    nearest_d = float("inf")
    for h in hazards:
        d = _grid_dist_m(survivor.grid_x, survivor.grid_y,
                         h.grid_x, h.grid_y, cell_size_m)
        if d < nearest_d:
            nearest_d, nearest_h = d, h

    if nearest_h is not None and nearest_d <= 120.0:
        sev = nearest_h.effective_severity
        pts = _SEV_HAZARD_POINTS.get(sev, 0)
        if nearest_d > 60.0:
            pts //= 2
        score += pts
        if nearest_h.lat is not None and survivor.lat is not None:
            loc_txt = f"{nearest_h.lat:.5f},{nearest_h.lon:.5f}"
        else:
            loc_txt = f"grid {nearest_h.grid_x},{nearest_h.grid_y}"
        reasons.append(
            f"{sev.label} {nearest_h.type.value.upper()} hazard "
            f"{nearest_d:.0f} m away ({loc_txt})"
        )

        if nearest_d <= 25.0:
            score += 10
            reasons.append("Survivor inside hazard zone — immediate "
                           "ground-team hazard")
        elif nearest_d <= 60.0:
            score += 5
            reasons.append("Survivor adjacent to hazard zone")

    # --- accessibility (drone proximity) ---------------------------------
    drone_d = _grid_dist_m(survivor.grid_x, survivor.grid_y,
                           drone_pos[0], drone_pos[1], cell_size_m)
    if drone_d <= 100.0:
        score += 10
        reasons.append(f"Drone {drone_d:.0f} m away — rapid re-verification")
    elif drone_d <= 250.0:
        score += 6
        reasons.append(f"Drone {drone_d:.0f} m away")
    else:
        score += 2
        reasons.append(f"Drone {drone_d:.0f} m away — long approach")

    if score >= P1_MIN:
        label = "P1"
    elif score >= P2_MIN:
        label = "P2"
    elif score >= P3_MIN:
        label = "P3"
    else:
        label = "P4"

    return PriorityResult(label=label, score=min(100.0, score), reasons=reasons)
