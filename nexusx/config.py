# -*- coding: utf-8 -*-
"""
Persistent JSON configuration (thread-safe, atomic writes).
On first start it imports the export pairs and theme from the legacy
UCeX v6 config (~/ucex_v6_config.json) so nothing configured there is lost.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from typing import Any, Dict, List

from .codex.constants import DEFAULT_EXPORT_PAIRS
from .paths import CONFIG_FILE, LEGACY_UCEX_CONFIG, ensure_app_dir

DEFAULTS: Dict[str, Any] = {
    "theme": "petrol",
    "language_email": "de",          # de | ro | en (ULaE emails were German)
    "visible_tabs": {},
    # code export
    "redact_secrets": True,
    "respect_gitignore": False,
    "md5_workers": 4,
    # link checker
    "link_timeout": 20,
    "link_workers": 8,
    "link_retries": 1,
    "check_fragments": True,
    "browser_channel": "chromium",   # chromium | msedge | chrome
    "browser_headless": False,       # ULaE default: visible for SSO reliability
    "keep_browser": True,
    "crawl_same_domain": True,
    "crawl_max_links": 300,
    # email
    "email": {
        "method": "outlook",          # outlook | smtp | eml
        "outlook_send_direct": False, # False = open the mail for review (ULaE behaviour)
        "to": "",
        "cc": "",
        "subject_links": "Ergebnisse der Link-Überprüfung (NexusX Report)",
        "subject_code": "NexusX Code Export",
        "signature": "",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_tls": True,
        "smtp_user": "",
        "smtp_from": "",
        "zip_attachments_over_mb": 15,
    },
    # tray / window
    "tray_enabled": True,
    "close_to_tray": False,
    "minimize_to_tray": False,
    "notify_on_finish": True,
    "geometry": "1480x900",
}


class ConfigManager:
    def __init__(self, path=CONFIG_FILE):
        self._path = path
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self.load()

    # ── persistence ───────────────────────────────────────────────────────────
    def load(self) -> None:
        with self._lock:
            data: Dict[str, Any] = {}
            if self._path.exists():
                try:
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            else:
                data = self._migrate_legacy()
            merged = copy.deepcopy(DEFAULTS)
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k].update(v)
                else:
                    merged[k] = v
            self._data = merged

    def _migrate_legacy(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if LEGACY_UCEX_CONFIG.exists():
            try:
                legacy = json.loads(LEGACY_UCEX_CONFIG.read_text(encoding="utf-8"))
                if isinstance(legacy.get("export_pairs"), list):
                    out["export_pairs"] = legacy["export_pairs"]
                if legacy.get("theme") in ("dark", "light"):
                    out["theme"] = legacy["theme"]
            except Exception:
                pass
        return out

    def save(self) -> None:
        with self._lock:
            ensure_app_dir()
            fd, tmp = tempfile.mkstemp(prefix="cfg_", suffix=".json", dir=str(self._path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, self._path)
            except Exception:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    # ── accessors ─────────────────────────────────────────────────────────────
    def get(self, key: str, default=None):
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))

    def set(self, key: str, value, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
            if save:
                self.save()

    def email(self) -> Dict[str, Any]:
        return self.get("email", copy.deepcopy(DEFAULTS["email"]))

    def set_email(self, **kw) -> None:
        e = self.email()
        e.update(kw)
        self.set("email", e)

    def get_export_pairs(self) -> List[Dict[str, str]]:
        pairs = self.get("export_pairs")
        return pairs if isinstance(pairs, list) else copy.deepcopy(DEFAULT_EXPORT_PAIRS)

    def set_export_pairs(self, pairs: List[Dict[str, str]]) -> None:
        self.set("export_pairs", pairs)

    def reset(self) -> None:
        with self._lock:
            self._data = copy.deepcopy(DEFAULTS)
            try:
                self._path.unlink()
            except Exception:
                pass
