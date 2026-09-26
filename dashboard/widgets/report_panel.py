"""Situation report panel (Step 15): live preview + JSON / CSV / print
exports.

The preview regenerates from :meth:`store.build_report` — every field comes
from actual store state, so an unmeasured value shows as ``N/A`` /
``NOT REPORTED`` in the export too.  Defaults to ``~/SIH_Reports``.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from theme import (
    BORDER,
    CYAN,
    FONT,
    GREEN,
    INSET_BG,
    TXT_DIM,
    TXT_MUTED,
    small_button_qss,
)
from utils.paths import EXPORT_DIR

# QPrinter lives in QtGui for PySide6; import guarded so a headless
# environment without print support still runs the panel.
try:
    from PySide6.QtGui import QPageSize, QPrinter
    from PySide6.QtPrintSupport import QPrintDialog
    _PRINT = True
except Exception:                                    # pragma: no cover
    _PRINT = False


class ReportPanel(QWidget):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._last_gen = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(5)

        head = QHBoxLayout()
        title = QLabel("SITUATION REPORT")
        title.setStyleSheet(f"color: {CYAN}; font-weight: bold;")
        title.setFont(QFont(FONT, 9))
        head.addWidget(title)
        head.addStretch()

        self.btn_refresh = QPushButton("REFRESH")
        self.btn_json = QPushButton("JSON")
        self.btn_csv = QPushButton("CSV")
        self.btn_print = QPushButton("PRINT")
        for btn in (self.btn_refresh, self.btn_json, self.btn_csv,
                    self.btn_print):
            btn.setFont(QFont(FONT, 8, QFont.Weight.Bold))
            btn.setStyleSheet(small_button_qss(CYAN))
            head.addWidget(btn)
        lay.addLayout(head)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont(FONT, 8))
        self.preview.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {INSET_BG}; "
            f"color: {TXT_MUTED}; border: 1px solid {BORDER}; "
            f"border-radius: 2px; padding: 4px; }}")
        lay.addWidget(self.preview, stretch=1)

        self.status = QLabel("export directory: " + EXPORT_DIR)
        self.status.setStyleSheet(f"color: {TXT_DIM};")
        self.status.setFont(QFont(FONT, 7))
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        self.btn_json.clicked.connect(self._export_json)
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_print.clicked.connect(self._print)

        # initial paint so the tab is never blank
        QTimer.singleShot(0, lambda: self.refresh(force=True))

    # ------------------------------------------------------------------
    def refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_gen < 2.0:
            return
        if not self.isVisible() and not force:
            return
        self._last_gen = now
        rep = self.store.build_report()
        self.preview.setPlainText(rep.to_text())

    # ------------------------------------------------------------------
    def _save_dialog(self, suffix: str) -> str | None:
        os.makedirs(EXPORT_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        default = os.path.join(EXPORT_DIR, f"sih_report_{stamp}{suffix}")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export situation report", default,
            f"Report (*{suffix})")
        return path or None

    def _export_json(self) -> None:
        path = self._save_dialog(".json")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.store.build_report().to_json())
            self.status.setText(f"saved: {path}")
            self.status.setStyleSheet(f"color: {GREEN};")
        except OSError as exc:
            self.status.setText(f"export failed: {exc}")
            self.status.setStyleSheet("color: #ff5a5a;")

    def _export_csv(self) -> None:
        path = self._save_dialog(".csv")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self.store.build_report().to_csv())
            self.status.setText(f"saved: {path}")
            self.status.setStyleSheet(f"color: {GREEN};")
        except OSError as exc:
            self.status.setText(f"export failed: {exc}")
            self.status.setStyleSheet("color: #ff5a5a;")

    def _print(self) -> None:
        if not _PRINT:
            self.status.setText("printing unavailable in this build")
            self.status.setStyleSheet("color: #ffb63d;")
            return
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
            doc = QTextDocument()
            doc.setPlainText(self.preview.toPlainText())
            dlg = QPrintDialog(printer, self)
            if dlg.exec():
                doc.print_(printer)
                self.status.setText("sent to printer / PDF dialog")
                self.status.setStyleSheet(f"color: {GREEN};")
        except Exception as exc:
            self.status.setText(f"print failed: {exc}")
            self.status.setStyleSheet("color: #ff5a5a;")
