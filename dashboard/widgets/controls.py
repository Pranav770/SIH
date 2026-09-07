from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
)
from PySide6.QtCore import Qt, Signal as pyqtSignal
from PySide6.QtGui import QFont


class Controls(QWidget):
    abort_signal = pyqtSignal()
    pause_signal = pyqtSignal()
    return_home_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(56)
        self.setStyleSheet("background-color: #1e1e2e; border-top: 1px solid #333;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(16)

        self.btn_abort = QPushButton("EMERGENCY ABORT")
        self.btn_abort.setStyleSheet(
            "background-color: #cc0000; color: white; font-weight: bold; "
            "padding: 8px 24px; border-radius: 4px; font-size: 14px;"
        )
        self.btn_abort.setFont(QFont("monospace", 12, QFont.Weight.Bold))
        self.btn_abort.clicked.connect(self.abort_signal.emit)

        self.btn_pause = QPushButton("PAUSE MISSION")
        self.btn_pause.setStyleSheet(
            "background-color: #555533; color: #ffdd00; font-weight: bold; "
            "padding: 8px 20px; border-radius: 4px; font-size: 12px;"
        )
        self.btn_pause.setFont(QFont("monospace", 10, QFont.Weight.Bold))
        self.btn_pause.clicked.connect(self.pause_signal.emit)

        self.btn_return = QPushButton("RETURN HOME")
        self.btn_return.setStyleSheet(
            "background-color: #333355; color: #88aaff; font-weight: bold; "
            "padding: 8px 20px; border-radius: 4px; font-size: 12px;"
        )
        self.btn_return.setFont(QFont("monospace", 10, QFont.Weight.Bold))
        self.btn_return.clicked.connect(self.return_home_signal.emit)

        layout.addWidget(self.btn_abort)
        layout.addWidget(self.btn_pause)
        layout.addWidget(self.btn_return)
        layout.addStretch()

        self.status_label = QPushButton("Connected")
        self.status_label.setStyleSheet(
            "background-color: #1a3a1a; color: #4f4; padding: 4px 12px; "
            "border-radius: 4px; font-weight: bold;"
        )
        self.status_label.setFont(QFont("monospace", 9))
        self.status_label.setEnabled(False)
        layout.addWidget(self.status_label)

    def set_connection_status(self, connected: bool):
        if connected:
            self.status_label.setText("Connected")
            self.status_label.setStyleSheet(
                "background-color: #1a3a1a; color: #4f4; padding: 4px 12px; "
                "border-radius: 4px; font-weight: bold;"
            )
        else:
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet(
                "background-color: #3a1a1a; color: #f66; padding: 4px 12px; "
                "border-radius: 4px; font-weight: bold;"
            )
