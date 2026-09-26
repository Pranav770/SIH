"""Glass-cockpit theme.

Central palette and shared stylesheet helpers for the EFIS-style "glass
cockpit" aesthetic applied across every GCS widget. Change a constant here and
the whole dashboard retheme follows.
"""

# -- Typefaces ------------------------------------------------------------
FONT = "monospace"

# -- Surfaces -------------------------------------------------------------
APP_BG    = "#091120"   # backdrop behind all panels
PANEL_BG  = "#0c1526"   # chrome bars: header / status / controls
INSET_BG  = "#0f1a2e"   # inset windows: badges, buttons, chips
TABLE_BG  = "#0b1424"   # tables
HEADER_BG = "#12233d"   # column headers, hover state
POPUP_BG  = "#0c1526ee" # translucent popups
BORDER    = "#1d3a5f"   # default border
BORDER_LT = "#29517f"   # bright border (hover / focus)
GRID_LINE = "#1d3a5f"

# -- Text -----------------------------------------------------------------
TXT_BRIGHT = "#f2fbff"
TXT_TEXT   = "#dfe9f5"
TXT_MUTED  = "#8fb3d9"
TXT_DIM    = "#5c7ba0"

# -- Glass accent palette -------------------------------------------------
CYAN    = "#4dd2ff"  # primary HUD / nav
GREEN   = "#3ddc84"  # good / armed / battery
AMBER   = "#ffb63d"  # caution / warnings
RED     = "#ff5a5a"  # alerts / abort
MAGENTA = "#ff58c0"  # targets / survivors / waypoints
BLUE    = "#4d9fff"  # flight / speed
TEAL    = "#2ee6a8"  # gps / navigation fix

# -- Hazard markers (glass-tinted) ---------------------------------------
HAZARD_COLORS = {
    "FIRE":   "#ff5a3c",
    "FLOOD":  "#35b8ff",
    "DEBRIS": "#ffc24d",
    "ELEC":   "#ffe34d",
    "STRUCT": "#ff4040",
    "LANDSL": "#c17a3f",
    "CHEM":   "#c46bff",
    "SMOKE":  "#9fb6cd",
}

# -- Reusable QSS helpers -------------------------------------------------


def badge_qss(accent: str, text_color: str = TXT_BRIGHT) -> str:
    """Glass datablock: inset navy chip with a colored accent edge."""
    return (
        f"background-color: {INSET_BG}; color: {text_color}; "
        f"border: 1px solid {BORDER}; border-left: 3px solid {accent}; "
        f"border-radius: 2px; padding: 4px 10px; font-weight: bold;"
    )


def button_qss(accent, text_color, bg=INSET_BG, hover=None, pressed=None):
    """Glass push-button: dark inset with a coloured base edge + hover/press states."""
    hover = hover or HEADER_BG
    pressed = pressed or TABLE_BG
    return (
        "QPushButton { background-color: %s; color: %s; font-weight: bold; "
        "border: 1px solid %s; border-bottom: 3px solid %s; border-radius: 2px; "
        "padding: 6px 20px; } "
        "QPushButton:hover { background-color: %s; } "
        "QPushButton:pressed { background-color: %s; border-bottom-width: 1px; }"
    ) % (bg, text_color, BORDER, accent, hover, pressed)


def small_button_qss(accent, text_color=TXT_TEXT) -> str:
    """Compact variant of button_qss (list rows, toolbars)."""
    return (
        f"QPushButton {{ background-color: {INSET_BG}; color: {text_color}; "
        f"border: 1px solid {BORDER}; border-bottom: 2px solid {accent}; "
        f"border-radius: 2px; padding: 2px 9px; font-weight: bold; }}"
        f"QPushButton:hover {{ background-color: {HEADER_BG}; }}"
        f"QPushButton:pressed {{ background-color: {TABLE_BG}; }}"
    )


# -- Semantic scales (severity / priority / health / provenance) ----------
SEVERITY_COLORS = {
    "LOW": TEAL, "MEDIUM": AMBER, "HIGH": "#ff8a3d", "CRITICAL": RED,
}
PRIORITY_COLORS = {"P1": RED, "P2": "#ff8a3d", "P3": CYAN, "P4": TXT_MUTED}
HEALTH_COLORS = {
    "healthy": GREEN, "degraded": AMBER, "offline": RED, "unknown": TXT_DIM,
}
LINK_COLORS = {
    "connected": GREEN, "degraded": AMBER, "disconnected": RED,
    "unknown": TXT_DIM,
}
SOURCE_COLORS = {"LIVE": GREEN, "SIM": AMBER, "SIMULATION": AMBER,
                 "UNKNOWN": TXT_DIM}
STALE_COLOR = AMBER


def health_color(state) -> str:
    return HEALTH_COLORS.get(str(getattr(state, "value", state)).lower(),
                             TXT_DIM)


def source_color(label: str) -> str:
    return SOURCE_COLORS.get(str(label).split(" ")[0].upper(), TXT_DIM)


def chip_qss(color: str, fg: str = TXT_BRIGHT) -> str:
    """Small glass status chip (state / provenance markers)."""
    return (
        f"background-color: {INSET_BG}; color: {fg}; border: 1px solid {BORDER}; "
        f"border-left: 3px solid {color}; border-radius: 2px; "
        f"padding: 1px 7px; font-weight: bold;"
    )


def panel_qss(accent: str = BORDER, bg: str = PANEL_BG) -> str:
    """Container frame for a titled panel section."""
    return (
        f"QFrame {{ background-color: {bg}; border: 1px solid {BORDER}; "
        f"border-top: 2px solid {accent}; border-radius: 3px; }}"
    )


def tab_qss() -> str:
    """QTabWidget / QTabBar styling for the right-hand dock."""
    return (
        f"QTabWidget::pane {{ border: 1px solid {BORDER}; "
        f"background-color: {PANEL_BG}; top: -1px; border-radius: 3px; }}"
        f"QTabBar::tab {{ background-color: {INSET_BG}; color: {TXT_MUTED}; "
        f"border: 1px solid {BORDER}; border-bottom: none; "
        f"padding: 6px 8px; margin-right: 1px; font-weight: bold; }}"
        f"QTabBar::tab:selected {{ color: {CYAN}; background-color: {HEADER_BG}; "
        f"border-top: 2px solid {CYAN}; }}"
        f"QTabBar::tab:hover:!selected {{ color: {TXT_TEXT}; "
        f"background-color: {HEADER_BG}; }}"
    )


def table_qss(sel_bg: str = BORDER_LT) -> str:
    """Shared data-table styling (matches survivor list / detection tables)."""
    return (
        f"QTableWidget {{ background-color: {TABLE_BG}; color: {TXT_TEXT}; "
        f"border: 1px solid {BORDER}; gridline-color: {GRID_LINE}; "
        f"selection-background-color: {sel_bg}; font-size: 11px; }}"
        f"QTableWidget::item {{ padding: 2px; }}"
        f"QHeaderView::section {{ background-color: {HEADER_BG}; color: {CYAN}; "
        f"border: 1px solid {BORDER}; padding: 3px; font-weight: bold; }}"
    )


def input_qss() -> str:
    """QLineEdit / QComboBox / QTextEdit chrome."""
    return (
        f"QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{ "
        f"background-color: {INSET_BG}; color: {TXT_TEXT}; "
        f"border: 1px solid {BORDER}; border-radius: 2px; padding: 4px 6px; "
        f"selection-background-color: {BORDER_LT}; }}"
        f"QComboBox:hover {{ border-color: {BORDER_LT}; }}"
        f"QComboBox QAbstractItemView {{ background-color: {INSET_BG}; "
        f"color: {TXT_TEXT}; selection-background-color: {HEADER_BG}; "
        f"border: 1px solid {BORDER_LT}; }}"
    )


# -- Global app stylesheet (scrollbars, tooltips) -------------------------
GLOBAL_QSS = """
QMainWindow { background-color: #091120; }
QScrollBar:vertical {
    background: #0f1a2e; width: 10px; border: 1px solid #1d3a5f;
    border-radius: 2px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #29517f; min-height: 24px; border-radius: 2px;
}
QScrollBar::handle:vertical:hover { background: #4dd2ff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    background: #0f1a2e; height: 10px; border: 1px solid #1d3a5f;
    border-radius: 2px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #29517f; min-width: 24px; border-radius: 2px;
}
QScrollBar::handle:horizontal:hover { background: #4dd2ff; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QToolTip {
    background-color: #0f1a2e; color: #dfe9f5;
    border: 1px solid #29517f; padding: 4px;
}
"""