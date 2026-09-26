"""Communication health panel (Step 11): per-link state, offline banner and
sync-queue visibility.

Link states come from message age derivation in the store; the offline
banner only appears when the store actually declared the link offline, and
it always shows how many queued records are waiting to sync — nothing is
pretended to be connected.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from models.comms import Link, LinkState, link_color
from theme import (
    AMBER,
    BORDER,
    FONT,
    INSET_BG,
    RED,
    TXT_BRIGHT,
    TXT_DIM,
    TXT_MUTED,
    TXT_TEXT,
)

_LINK_ORDER = ["TELEMETRY", "GROUND STATION", "5G", "WIFI", "MESH"]

_STATE_STYLE = {
    LinkState.CONNECTED: "#3ddc84",
    LinkState.DEGRADED: "#ffb63d",
    LinkState.DISCONNECTED: "#ff5a5a",
    LinkState.UNKNOWN: "#5c7ba0",
}


def _fmt_sync(ts) -> str:
    if ts is None:
        return "NEVER"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%SZ")


class CommsPanel(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # -- offline banner (hidden while online) -------------------------
        self.banner = QLabel("COMMUNICATION LOST — AUTONOMOUS OPERATION")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setFont(QFont(FONT, 9, QFont.Weight.Bold))
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            f"background-color: #3a1015; color: {RED}; "
            f"border: 1px solid {RED}; border-radius: 3px; padding: 6px;")
        self.banner.hide()
        lay.addWidget(self.banner)

        self.autonomy = QLabel("")
        self.autonomy.setStyleSheet(f"color: {TXT_TEXT};")
        self.autonomy.setFont(QFont(FONT, 8))
        self.autonomy.setWordWrap(True)
        self.autonomy.hide()
        lay.addWidget(self.autonomy)

        # -- links ---------------------------------------------------------
        head = QLabel("LINK HEALTH")
        head.setStyleSheet(f"color: {AMBER}; font-weight: bold;")
        head.setFont(QFont(FONT, 9))
        lay.addWidget(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self._rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for i, name in enumerate(_LINK_ORDER):
            n = QLabel(name)
            n.setStyleSheet(f"color: {TXT_MUTED};")
            n.setFont(QFont(FONT, 8))
            state = QLabel("·")
            state.setFont(QFont(FONT, 8, QFont.Weight.Bold))
            state.setFixedWidth(84)
            state.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail = QLabel("--")
            detail.setStyleSheet(f"color: {TXT_DIM};")
            detail.setFont(QFont(FONT, 7))
            grid.addWidget(n, i, 0)
            grid.addWidget(state, i, 1)
            grid.addWidget(detail, i, 2)
            self._rows[name] = (n, state, detail)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        # -- sync queue -----------------------------------------------------
        shead = QLabel("OFFLINE SYNC QUEUE")
        shead.setStyleSheet(f"color: {AMBER}; font-weight: bold;")
        shead.setFont(QFont(FONT, 9))
        lay.addWidget(shead)

        self.sync_rows: dict[str, QLabel] = {}
        sg = QGridLayout()
        sg.setHorizontalSpacing(6)
        for i, (key, label) in enumerate((
            ("last", "LAST SYNC"),
            ("pending", "PENDING RECORDS"),
            ("queued", "QUEUED ALERTS"),
            ("storage", "STORAGE"),
        )):
            k = QLabel(label)
            k.setStyleSheet(f"color: {TXT_MUTED};")
            k.setFont(QFont(FONT, 8))
            v = QLabel("--")
            v.setStyleSheet(f"color: {TXT_BRIGHT}; font-weight: bold;")
            v.setFont(QFont(FONT, 8))
            v.setAlignment(Qt.AlignmentFlag.AlignRight)
            r, c = divmod(i, 2)
            sg.addWidget(k, r, c * 2)
            sg.addWidget(v, r, c * 2 + 1)
            self.sync_rows[key] = v
        sg.setColumnStretch(0, 1)
        sg.setColumnStretch(2, 1)
        lay.addLayout(sg)

        self.note = QLabel("")
        self.note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
        self.note.setFont(QFont(FONT, 7))
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        comms = self.store.comms
        sync = self.store.sync

        # offline banner
        if comms.offline:
            self.banner.show()
            self.autonomy.setText(self.store.autonomy_text)
            self.autonomy.show()
        else:
            self.banner.hide()
            self.autonomy.hide()

        # links (only show what the store knows about; unseen stay "·")
        for name, (n_lbl, st_lbl, det_lbl) in self._rows.items():
            link = comms.links.get(name)
            if link is None:
                st_lbl.setText("·")
                st_lbl.setStyleSheet(f"color: {TXT_DIM}; font-weight: bold;")
                det_lbl.setText("not reported")
                det_lbl.setStyleSheet(f"color: {TXT_DIM};")
                continue
            color = _STATE_STYLE[link.state]
            st_lbl.setText(link.state.label)
            st_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold;")
            if link.last_rx is not None:
                # only some links carry an explicit timestamp; the age
                # derivation links already embed their age in `detail`
                det_lbl.setText(
                    f"{link.detail} · last data {link.age_s:.1f}s ago")
            else:
                det_lbl.setText(link.detail)
            det_color = (TXT_DIM if link.state == LinkState.UNKNOWN
                         else TXT_MUTED)
            det_lbl.setStyleSheet(f"color: {det_color};")

        # sync queue
        self.sync_rows["last"].setText(_fmt_sync(comms.last_sync))
        self.sync_rows["pending"].setText(str(sync.pending))
        self.sync_rows["queued"].setText(str(sync.pending_alerts))
        ok = sync.storage_ok
        self.sync_rows["storage"].setText(
            "ACTIVE" if ok else "UNAVAILABLE" if ok is False else "N/A")
        self.sync_rows["storage"].setStyleSheet(
            "color: %s; font-weight: bold;" %
            ("#3ddc84" if ok else "#ff5a5a" if ok is False else TXT_DIM))

        if sync.pending:
            self.note.setText(
                f"{sync.pending} record(s) buffered locally — they sync "
                f"automatically when the link returns")
            self.note.setStyleSheet(f"color: {AMBER}; font-style: italic;")
        else:
            self.note.setText("queue empty — nothing pending")
            self.note.setStyleSheet(f"color: {TXT_DIM}; font-style: italic;")
