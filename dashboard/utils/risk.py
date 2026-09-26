"""Rule-based hazard risk model (Step 8).

Transparent, configurable and explainable — every severity comes with the
reasons that produced it so judges can audit the logic.  When the backend
sends its own severity the backend value always wins; this model only fills
gaps (and powers the simulation).
"""

from __future__ import annotations

from models.detection import Severity
from models.hazard import HazardType

# Base severity per hazard class — configuration, not AI output.
BASE_SEVERITY: dict[HazardType, Severity] = {
    HazardType.CHEMICAL: Severity.CRITICAL,
    HazardType.ELECTRICAL: Severity.CRITICAL,
    HazardType.FIRE: Severity.HIGH,
    HazardType.FLOOD: Severity.HIGH,
    HazardType.LANDSLIDE: Severity.HIGH,
    HazardType.STRUCTURAL: Severity.MEDIUM,
    HazardType.SMOKE: Severity.MEDIUM,
    HazardType.DEBRIS: Severity.MEDIUM,
}

HIGH_CONF = 0.90
LOW_CONF = 0.50
SURVIVOR_LINK_M = 50.0     # hazard near a survivor escalates it


def assess_hazard_severity(
    htype: HazardType,
    confidence: float = 0.0,
    survivor_near_m: float | None = None,
) -> tuple[Severity, list[str]]:
    """Return (severity, reasons). Deterministic and ordered."""
    reasons: list[str] = []
    sev = BASE_SEVERITY.get(htype, Severity.MEDIUM)
    reasons.append(f"{htype.value.upper()} base risk: {sev.label}")

    conf = max(0.0, min(1.0, float(confidence or 0.0)))
    if conf >= HIGH_CONF:
        sev = sev.upgrade()
        reasons.append(f"Detection confidence {conf:.0%} ≥ {HIGH_CONF:.0%}"
                       f" → escalated to {sev.label}")
    elif conf and conf < LOW_CONF:
        sev = sev.downgrade()
        reasons.append(f"Detection confidence {conf:.0%} < {LOW_CONF:.0%}"
                       f" → de-escalated to {sev.label}")

    if survivor_near_m is not None and survivor_near_m <= SURVIVOR_LINK_M:
        before = sev
        sev = sev.upgrade()
        reasons.append(f"Survivor {survivor_near_m:.0f} m away"
                       f" ({'+' if sev.rank > before.rank else 'no change'}"
                       f" → {sev.label})")

    return sev, reasons
