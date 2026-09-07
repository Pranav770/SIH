from enum import Enum


class MissionPhase(Enum):
    IDLE = "idle"
    TAKEOFF = "takeoff"
    SCANNING = "scanning"
    RETURNING = "returning"
    LANDING = "landing"
    COMPLETE = "complete"
    ABORTED = "aborted"


class MissionState:
    def __init__(self):
        self.phase = MissionPhase.IDLE
        self.progress = 0.0
        self.total_grid_cells = 0
        self.scanned_cells = 0
        self.survivors_found = 0
        self.hazards_found = 0

    @property
    def phase_text(self) -> str:
        labels = {
            MissionPhase.IDLE: "Idle",
            MissionPhase.TAKEOFF: "Takeoff",
            MissionPhase.SCANNING: "Scanning",
            MissionPhase.RETURNING: "Returning Home",
            MissionPhase.LANDING: "Landing",
            MissionPhase.COMPLETE: "Mission Complete",
            MissionPhase.ABORTED: "Mission Aborted",
        }
        return labels.get(self.phase, "Unknown")

    def update(self, phase: str, progress: float, total: int = 0, scanned: int = 0):
        phase_map = {p.value: p for p in MissionPhase}
        self.phase = phase_map.get(phase, MissionPhase.IDLE)
        self.progress = progress
        self.total_grid_cells = total
        self.scanned_cells = scanned
