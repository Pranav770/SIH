"""Telemetry and GPS data structures.

``DroneTelemetry`` is a *TypedDict* — the single wire schema produced by both
the live MAVLink thread and the simulation engine.  Widgets read plain dicts
through the dashboard store; the TypedDict documents the contract without
duplicating a second runtime schema.

``GPSStatus`` / ``EKFStatus`` are derived state objects maintained by the
store from ``GPS_RAW_INT`` / ``EKF_STATUS_REPORT`` messages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TypedDict

# MAVLink GPS fix_type values (GPS_RAW_INT.fix_type)
FIX_LABELS = {
    0: "NO GPS",
    1: "NO FIX",
    2: "2D",
    3: "3D",
    4: "DGPS",
    5: "RTK FLOAT",
    6: "RTK FIXED",
}

# GPS considered "fresh" for navigation decisions (seconds)
GPS_STALE_S = 2.0


class DroneTelemetry(TypedDict, total=False):
    """Latest-value telemetry merge (each key refreshed when its message
    arrives; absent keys mean *not reported yet*)."""

    # HEARTBEAT
    mode: str
    armed: bool
    system_status: int
    autopilot: str
    # SYS_STATUS
    battery: int          # percent remaining (0-100, -1 unknown)
    voltage: int          # millivolts
    current: int          # centiamps (-1 unknown)
    # GPS_RAW_INT
    gps_fix: int          # 0..6
    gps_satellites: int
    gps_hdop: float       # unitless HDOP (eph / 10)
    gps_accuracy_m: float # horizontal accuracy, metres
    lat: float            # degrees
    lon: float            # degrees
    # GLOBAL_POSITION_INT
    relative_alt: float   # metres above home
    vx: float             # m/s (NED)
    vy: float
    vz: float
    # VFR_HUD
    heading: int          # degrees 0..359
    groundspeed: float    # m/s
    alt: float            # metres AMSL
    climb: float          # m/s
    # ATTITUDE
    roll: float           # degrees
    pitch: float
    yaw: float
    # LOCAL_POSITION_NED
    x: float
    y: float
    z: float
    # EKF_STATUS_REPORT (normalised)
    ekf_reported: bool
    ekf_flags: int
    ekf_horiz_acc: float      # metres
    ekf_vel_err: float        # m/s
    # derived nav hints (simulation / companion may set these directly)
    nav_sources: list         # e.g. ["gps", "ekf", "imu", "vo", "of", "lidar"]
    gps_denied: bool
    # MISSION_CURRENT
    wp_seq: int
    # provenance
    source: str            # "live" | "sim"


@dataclass
class GPSStatus:
    """Derived GPS health snapshot (Step 4 — navigation health section)."""

    fix_type: int = 0
    satellites: int | None = None
    hdop: float | None = None          # unitless
    accuracy_m: float | None = None    # horizontal accuracy, metres
    lat: float | None = None
    lon: float | None = None
    last_rx: float | None = field(default=None, repr=False)  # monotonic

    @property
    def fix_label(self) -> str:
        return FIX_LABELS.get(self.fix_type, f"UNKNOWN ({self.fix_type})")

    @property
    def age_s(self) -> float | None:
        if self.last_rx is None:
            return None
        return time.monotonic() - self.last_rx

    @property
    def age_text(self) -> str:
        age = self.age_s
        if age is None:
            return "NO DATA"
        return f"{age:.1f} s ago"

    @property
    def stale(self) -> bool:
        age = self.age_s
        return age is None or age > GPS_STALE_S

    @property
    def has_fix(self) -> bool:
        return self.fix_type >= 3

    @property
    def healthy(self) -> bool:
        """3D (or better) fix with fresh data and sane satellite count."""
        if not self.has_fix or self.stale:
            return False
        if self.satellites is not None and self.satellites < 6:
            return False
        return True

    @property
    def state(self) -> str:
        """OK / STALE / LOST — never claims health without data."""
        if self.last_rx is None:
            return "UNKNOWN"
        if not self.has_fix:
            return "LOST"
        if self.stale:
            return "STALE"
        return "OK"


@dataclass
class EKFStatus:
    """Normalised EKF health (MAVLink EKF_STATUS_REPORT)."""

    reported: bool = False
    flags: int = 0
    horiz_acc: float | None = None     # metres
    vel_err: float | None = None       # m/s
    last_rx: float | None = field(default=None, repr=False)

    # MAVLink EKF_STATUS_REPORT.flags bit definitions
    BIT_HORIZ_POS_ABS = 1
    BIT_VERT_POS_ABS = 2
    BIT_HORIZ_VEL_ABS = 4
    BIT_VERT_VEL_ABS = 8
    BIT_YAW = 256
    BIT_CONST_POS_MODE = 1024

    @property
    def age_s(self) -> float | None:
        if self.last_rx is None:
            return None
        return time.monotonic() - self.last_rx

    @property
    def healthy(self) -> bool:
        if not self.reported or self.age_s is None or self.age_s > 5.0:
            return False
        if self.flags & self.BIT_CONST_POS_MODE:
            return False
        required = self.BIT_HORIZ_POS_ABS | self.BIT_VERT_POS_ABS
        return (self.flags & required) == required

    @property
    def dead_reckoning(self) -> bool:
        """EKF is navigating without absolute position aid (const-pos mode)."""
        return self.reported and bool(self.flags & self.BIT_CONST_POS_MODE)

    @property
    def state(self) -> str:
        if not self.reported:
            return "UNKNOWN"
        if self.age_s is None or self.age_s > 5.0:
            return "STALE"
        if self.healthy:
            return "OK"
        if self.dead_reckoning:
            return "DEAD RECKONING"
        return "DEGRADED"
