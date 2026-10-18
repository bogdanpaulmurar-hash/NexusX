# -*- coding: utf-8 -*-
"""Central file-system locations used by NexusX."""
from __future__ import annotations

import datetime
from pathlib import Path

HOME = Path.home()
APP_DIR = HOME / ".nexusx"
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "NexusX_log.txt"
SOURCES_JSON = APP_DIR / "sources_catalog.json"

# Kept identical to ULaE v2.0 so existing SSO cookies / sessions keep working.
PLAYWRIGHT_PROFILE = HOME / ".ulae_playwright_profile"

# Legacy files (read-only migration sources)
LEGACY_UCEX_CONFIG = HOME / "ucex_v6_config.json"
LEGACY_ULAE_SOURCES_JSON = HOME / ".ulae_sources_catalog.json"

# Corporate defaults from the original tools (used only if they exist)
SIEMENS_ONEDRIVE = HOME / "OneDrive - Siemens AG"
MOBILE_GUIDES_DIR = SIEMENS_ONEDRIVE / "GSP SpecialTopics_OneDrive" / "MobileGuidesupdates"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICON_ICO = ASSETS_DIR / "nexusx.ico"
ICON_PNG = ASSETS_DIR / "nexusx.png"


def ensure_app_dir() -> Path:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DIR


def default_report_dir() -> Path:
    """Dated report folder; prefers the ULaE corporate location when present."""
    base = MOBILE_GUIDES_DIR / "Exports with NexusX"
    if not MOBILE_GUIDES_DIR.exists():
        base = HOME / "Desktop" / "NexusX_Reports"
    return base / datetime.datetime.now().strftime("%Y%m%d")


def default_desktop() -> Path:
    d = HOME / "Desktop"
    return d if d.exists() else HOME
