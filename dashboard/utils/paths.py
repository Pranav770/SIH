"""Filesystem locations used by the GCS (local store, default exports)."""

from __future__ import annotations

import os

_DASHBOARD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Disk-backed local storage (sync queue) — proves offline persistence.
DATA_DIR = os.path.join(_DASHBOARD_DIR, ".local_store")

# Default folder offered by report/export dialogs.
EXPORT_DIR = os.path.join(os.path.expanduser("~"), "SIH_Reports")
