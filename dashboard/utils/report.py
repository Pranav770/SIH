"""Automatic situation report (Step 15).

Built exclusively from the store's actual state — when something has not
been measured the report says so instead of inventing values.  Exportable
as JSON, CSV and a printable text view (Ctrl+P / PDF via the report panel).
"""

from __future__ import annotations

import csv
import io
import json
import time
from dataclasses import dataclass, field


@dataclass
class SituationReport:
    mission_id: str
    generated_at: str
    area_covered: str
    coverage_pct: str
    survivors_detected: int
    survivor_lines: list[str] = field(default_factory=list)
    hazards: dict = field(default_factory=dict)          # class -> count
    hazard_lines: list[str] = field(default_factory=list)
    critical_alerts: int = 0
    alert_lines: list[str] = field(default_factory=list)
    gps_normal_pct: float = 0.0
    gps_denied_pct: float = 0.0
    communication: str = "UNKNOWN"
    pending_records: int = 0
    ai_line: str = "NOT REPORTED"
    data_sources: str = "LIVE"
    recommendations: list[str] = field(default_factory=list)

    # -- exports ----------------------------------------------------------
    def to_text(self) -> str:
        lines = [
            "=" * 58,
            "DISASTER SITUATION REPORT",
            "=" * 58,
            f"Mission      : {self.mission_id}",
            f"Time         : {self.generated_at}",
            f"Data source  : {self.data_sources}",
            "",
            f"Area covered : {self.area_covered}  ({self.coverage_pct})",
            f"Survivors detected: {self.survivors_detected}",
        ]
        lines += [f"  - {s}" for s in self.survivor_lines] or ["  - none"]
        lines += ["", "Hazards:"]
        lines += [f"  {k}: {v}" for k, v in self.hazards.items()] or ["  none"]
        lines += [f"  {h}" for h in self.hazard_lines]
        lines += [
            "",
            f"Critical alerts: {self.critical_alerts}",
        ]
        lines += [f"  - {a}" for a in self.alert_lines] or ["  - none"]
        lines += [
            "",
            "GPS availability:",
            f"  {self.gps_normal_pct:.0f}% normal",
            f"  {self.gps_denied_pct:.0f}% GPS-denied",
            "",
            f"Communication: {self.communication}",
            f"Unsynchronised records: {self.pending_records}",
            f"On-device AI: {self.ai_line}",
            "",
            "Recommended response:",
        ]
        lines += [f"  * {r}" for r in self.recommendations] or ["  * monitor"]
        lines += ["=" * 58]
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(self.__dict__, indent=2, default=str)

    def to_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["section", "item", "value"])
        w.writerow(["meta", "mission", self.mission_id])
        w.writerow(["meta", "time", self.generated_at])
        w.writerow(["meta", "data_source", self.data_sources])
        w.writerow(["coverage", "area", self.area_covered])
        w.writerow(["coverage", "pct", self.coverage_pct])
        w.writerow(["survivors", "count", self.survivors_detected])
        for s in self.survivor_lines:
            w.writerow(["survivors", "detail", s])
        for k, v in self.hazards.items():
            w.writerow(["hazards", k, v])
        w.writerow(["alerts", "critical", self.critical_alerts])
        for a in self.alert_lines:
            w.writerow(["alerts", "detail", a])
        w.writerow(["gps", "normal_pct", f"{self.gps_normal_pct:.0f}"])
        w.writerow(["gps", "denied_pct", f"{self.gps_denied_pct:.0f}"])
        w.writerow(["comms", "state", self.communication])
        w.writerow(["comms", "pending", self.pending_records])
        w.writerow(["ai", "status", self.ai_line])
        for r in self.recommendations:
            w.writerow(["recommendation", "-", r])
        return buf.getvalue()


def build_report(
    mission_id: str,
    coverage_text: str,
    coverage_pct: str,
    survivors: list,
    hazards: list,
    critical_alerts: int,
    alerts: list,
    gps_normal_pct: float,
    gps_denied_pct: float,
    communication: str,
    pending_records: int,
    ai_line: str,
    data_sources: str,
) -> SituationReport:
    rep = SituationReport(
        mission_id=mission_id,
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        area_covered=coverage_text,
        coverage_pct=coverage_pct,
        survivors_detected=len(survivors),
        critical_alerts=critical_alerts,
        gps_normal_pct=gps_normal_pct,
        gps_denied_pct=gps_denied_pct,
        communication=communication,
        pending_records=pending_records,
        ai_line=ai_line,
        data_sources=data_sources,
    )

    # survivors, best priority first
    ordered = sorted(survivors, key=lambda s: s.priority)
    for s in ordered:
        conf = f"{s.confidence:.1%}"
        mode = s.fusion_mode
        reason = s.priority_reasons[1] if len(s.priority_reasons) > 1 \
            else (s.priority_reasons[0] if s.priority_reasons else "")
        rep.survivor_lines.append(
            f"{s.priority} {s.id} — conf {conf}, sensors {mode}, "
            f"{s.location_text} — {reason}"
        )

    # hazards by class
    counts: dict[str, int] = {}
    for h in hazards:
        counts[h.class_label] = counts.get(h.class_label, 0) + 1
    rep.hazards = dict(sorted(counts.items()))
    critical = [h for h in hazards
                if h.effective_severity.rank >= 3]
    for h in sorted(critical, key=lambda x: -x.effective_severity.rank)[:5]:
        rep.hazard_lines.append(
            f"! {h.class_label} CRITICAL at {h.location_text}"
        )

    for a in sorted((a for a in alerts if not a.cleared),
                    key=lambda x: x.priority.value)[:5]:
        rep.alert_lines.append(f"{a.priority.label} {a.title} @ {a.location}")

    # recommendations — transparent, rule-derived
    if ordered:
        top = ordered[0]
        rep.recommendations.append(
            f"Prioritize {top.id} ({top.priority}) — "
            f"{top.priority_reasons[-1] if top.priority_reasons else 'survivor detected'}"
        )
    for h in critical[:2]:
        rep.recommendations.append(
            f"Avoid {h.class_label} zone at {h.location_text}"
        )
    if gps_denied_pct >= 15:
        rep.recommendations.append(
            f"GPS-denied navigation used {gps_denied_pct:.0f}% of the mission "
            "— verify inertial/visual aiding before next sortie"
        )
    if communication.lower().startswith(("intermittent", "lost", "degraded")):
        rep.recommendations.append(
            "Communication intermittent — queued records will sync on reconnect"
        )
    if not rep.recommendations:
        rep.recommendations.append(
            "No survivors detected — continue planned search pattern"
        )
    return rep
