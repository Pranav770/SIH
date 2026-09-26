"""GPS / GPS-denied navigation state (Step 4).

``NavigationState`` is a clean abstraction between the raw sensor data and
the UI: it says *which positioning sources are actually in use right now*.
It is fed from real data (GPS fix/age + EKF health + explicit source hints
from the companion computer or simulation) — never from a display-only
label, so a genuine in-flight GPS loss produces the same state as the demo
scenario.

Sources the backend never reports stay ``UNKNOWN`` (grey in the UI); the
dashboard does not claim visual odometry / optical flow / LiDAR are active
unless something actually reported them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from models.telemetry import GPSStatus, EKFStatus


class PositionSource(Enum):
    GPS = "gps"
    IMU = "imu"
    EKF = "ekf"
    VO = "vo"                # visual odometry
    OPTICAL_FLOW = "of"
    LIDAR = "lidar"
    VSLAM = "vslam"

    @property
    def label(self) -> str:
        return {
            "gps": "GPS",
            "imu": "IMU",
            "ekf": "EKF",
            "vo": "VISUAL ODO",
            "of": "OPTICAL FLOW",
            "lidar": "LIDAR",
            "vslam": "VISUAL SLAM",
        }[self.value]


class SourceState(Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    UNKNOWN = "unknown"


# aliases accepted from backend/simulation payloads
_SOURCE_ALIASES = {
    "gps": PositionSource.GPS,
    "imu": PositionSource.IMU,
    "ekf": PositionSource.EKF,
    "vo": PositionSource.VO,
    "vio": PositionSource.VO,
    "visual_odometry": PositionSource.VO,
    "of": PositionSource.OPTICAL_FLOW,
    "optical_flow": PositionSource.OPTICAL_FLOW,
    "opticalflow": PositionSource.OPTICAL_FLOW,
    "lidar": PositionSource.LIDAR,
    "vslam": PositionSource.VSLAM,
    "slam": PositionSource.VSLAM,
    "visual_slam": PositionSource.VSLAM,
}


@dataclass
class NavigationState:
    gps_denied: bool = False
    degraded: bool = False
    label: str = "UNKNOWN"            # e.g. "GPS + EKF"
    reason: str = ""                  # human-readable derivation reason
    sources: dict[PositionSource, SourceState] = field(default_factory=dict)
    reported: bool = False            # True once any source info exists

    def state_of(self, src: PositionSource) -> SourceState:
        return self.sources.get(src, SourceState.UNKNOWN)

    @property
    def banner(self) -> str:
        if not self.reported:
            return "NAVIGATION: AWAITING DATA"
        if self.gps_denied:
            return "GPS-DENIED NAVIGATION: ACTIVE"
        if self.degraded:
            return "NAVIGATION: DEGRADED"
        return "NAVIGATION: GPS NOMINAL"


def derive_navigation(
    gps: GPSStatus,
    ekf: EKFStatus,
    reported_sources: list[str] | None = None,
    explicit_denied: bool | None = None,
) -> NavigationState:
    """Pure derivation used identically for LIVE telemetry and simulation.

    ``reported_sources`` — source names the backend/simulation explicitly
    reported (e.g. ["ekf", "imu", "vo", "of", "lidar"]).
    ``explicit_denied``  — backend-provided GPS-denied flag (wins if set).
    """
    state = NavigationState()

    src_map: dict[PositionSource, SourceState] = {}
    named: set[PositionSource] = set()
    for raw in reported_sources or []:
        ps = _SOURCE_ALIASES.get(str(raw).lower().strip())
        if ps is not None:
            named.add(ps)

    gps_ok = gps.healthy
    stale_gps = gps.last_rx is None or gps.stale

    if explicit_denied is not None:
        gps_denied = explicit_denied
    elif gps.last_rx is None:
        # no GPS data at all — link problem, do not claim GPS-denied nav
        gps_denied = False
    elif stale_gps:
        # data exists but is stale: staleness is a *link* concern, not a
        # GPS-loss assertion (see telemetry-stale / comm alerts instead)
        gps_denied = False
    else:
        gps_denied = not gps.has_fix

    # -- source states ----------------------------------------------------
    if gps.last_rx is None:
        src_map[PositionSource.GPS] = SourceState.UNKNOWN
    elif gps_denied:
        # a fix may still be reported, but navigation must not trust it:
        # standby while the receiver reports, lost when it reports nothing
        src_map[PositionSource.GPS] = (SourceState.STANDBY if gps.has_fix
                                       else SourceState.UNKNOWN)
    elif gps_ok:
        src_map[PositionSource.GPS] = SourceState.ACTIVE
    elif gps.stale:
        src_map[PositionSource.GPS] = SourceState.STANDBY   # stale fix
    elif gps.has_fix:
        src_map[PositionSource.GPS] = SourceState.STANDBY
    else:
        src_map[PositionSource.GPS] = SourceState.UNKNOWN   # lost

    if ekf.reported:
        if ekf.healthy:
            src_map[PositionSource.EKF] = SourceState.ACTIVE
        elif ekf.dead_reckoning or gps_denied:
            src_map[PositionSource.EKF] = SourceState.ACTIVE  # DR aid
        else:
            src_map[PositionSource.EKF] = SourceState.STANDBY
        src_map[PositionSource.IMU] = SourceState.ACTIVE
    else:
        src_map[PositionSource.EKF] = SourceState.UNKNOWN
        src_map[PositionSource.IMU] = SourceState.UNKNOWN

    # Visual / ranging sources: ACTIVE only when explicitly reported.
    for ps in (PositionSource.VO, PositionSource.OPTICAL_FLOW,
               PositionSource.LIDAR, PositionSource.VSLAM):
        if ps in named:
            src_map[ps] = SourceState.ACTIVE
        else:
            src_map[ps] = SourceState.UNKNOWN

    state.sources = src_map
    state.reported = (
        gps.last_rx is not None or ekf.reported or bool(reported_sources)
    )
    state.gps_denied = gps_denied
    state.degraded = (not gps_denied) and (not ekf.healthy) and ekf.reported

    # -- active-source label ---------------------------------------------
    active = [ps for ps, st in src_map.items() if st is SourceState.ACTIVE]
    order = [PositionSource.GPS, PositionSource.EKF, PositionSource.IMU,
             PositionSource.VO, PositionSource.VSLAM,
             PositionSource.OPTICAL_FLOW, PositionSource.LIDAR]
    active_sorted = [ps for ps in order if ps in active]

    if gps_denied:
        # denied wins: never overwrite this with a healthy-GPS reason
        fallback = [ps for ps in active_sorted
                    if ps not in (PositionSource.GPS,)]
        if fallback:
            state.label = " + ".join(ps.label for ps in fallback)
            state.reason = "GPS-denied — dead reckoning on " + \
                state.label
        else:
            state.label = "IMU + EKF (DEAD RECKONING)"
            state.reason = "GPS-denied — no visual/ranging aid reported"
    elif active_sorted:
        state.label = " + ".join(ps.label for ps in active_sorted)
        state.reason = f"GPS {gps.fix_label}, {gps.age_text}"
    elif gps.last_rx is not None and gps.stale:
        state.label = "GPS DATA STALE"
        state.reason = f"Last GPS update {gps.age_text} — link problem, " \
                       "not a GPS fix loss"
    else:
        state.label = "UNKNOWN"
        state.reason = "No positioning data received yet"

    return state
