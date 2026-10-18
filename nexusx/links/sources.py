# -*- coding: utf-8 -*-
"""
SharePoint & Sources catalog (ULaE v2.0 sources_manager.py).
Same Excel/JSON behaviour; reuses the existing ULaE catalog (Excel or JSON) if present.
Improvements: stable unique ids, URL→local OneDrive resolution also searches the
synced "OneDrive - Siemens AG" tree and decodes SharePoint "sourcedoc"/"file=" links.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..paths import LEGACY_ULAE_SOURCES_JSON, MOBILE_GUIDES_DIR, SIEMENS_ONEDRIVE, SOURCES_JSON, ensure_app_dir

DOCS_DIR = MOBILE_GUIDES_DIR / "Dokumentationen"
_SP = "https://siemens.sharepoint.com/teams/P0003139/Shared%20Documents/Tools%20and%20Templates/Field%20Service%20Industry/"

DEFAULT_SOURCES: List[Dict[str, Any]] = [
    {"name": "InternalFSE Guide mMobile", "type": "SharePoint DOCX", "url": _SP + "InternalFSE_Guide_mMobile.docx?Web=1",
     "local_path": str(DOCS_DIR / "InternalFSE_Guide_mMobile.docx"), "description": "Hauptleitfaden mMobile für FSE"},
    {"name": "InternalFSE Guide Windows", "type": "SharePoint DOCX", "url": _SP + "InternalFSE_Guide_Windows.docx?Web=1",
     "local_path": str(DOCS_DIR / "InternalFSE_Guide_Windows.docx"), "description": "Leitfaden Windows Client für FSE"},
    {"name": "Dokumentations-Überprüfung FSI Komplett", "type": "Master Audit DOCX",
     "url": _SP + "Dokumentations_Überprüfung_FSI_komplett.docx",
     "local_path": str(DOCS_DIR / "Dokumentations_Überprüfung_FSI_komplett.docx"),
     "description": "Master-Übersicht aller FSI Dokumentationen und Links"},
    {"name": "Guide GSP Mobile Background Sync", "type": "Technical Guide",
     "url": _SP + "Guide_GSP_Mobile_FSI_Description_Background_Sync.docx?Web=1",
     "local_path": str(DOCS_DIR / "Guide_GSP_Mobile_FSI_Description_Background_Sync.docx"),
     "description": "Hintergrund-Synchronisation Beschreibung"},
    {"name": "Internal Mobile Solution Guide", "type": "General Guide",
     "url": _SP + "Internal%20Mobile%20Solution%20Guide.docx",
     "local_path": str(DOCS_DIR / "Internal Mobile Solution Guide.docx"), "description": "Mobile Solution Leitfaden intern"},
    {"name": "Release Notes FSI (SharePoint File)", "type": "Text Release Notes", "url": _SP + "Release%20Notes%20FSI.txt",
     "local_path": str(DOCS_DIR / "siemens.sharepoint.com_teams_P0003139_Shared Documents_Tools and Templates_Field Service Industry_Release Notes FSI.txt.pdf"),
     "description": "FSI Production Release Notes"},
    {"name": "Release Notes FSI UAT (SharePoint File)", "type": "Text Release Notes", "url": _SP + "Release%20Notes%20FSI%20UAT.txt",
     "local_path": str(DOCS_DIR / "siemens.sharepoint.com_teams_P0003139_Shared Documents_Tools and Templates_Field Service Industry_Release Notes FSI UAT.txt.pdf"),
     "description": "FSI UAT Release Notes"},
    {"name": "Wiki: How to get external FSE to work with mobile GSP Apps", "type": "Wiki Page",
     "url": "https://wiki.siemens.com/display/en/How+to+get+an+external+FSE+to+work+with+the+mobile+GSP+Apps",
     "local_path": "", "description": "Siemens Confluence Wiki Anleitung"},
    {"name": "Apps, Templates und Interfaces Portal", "type": "SharePoint Portal Page",
     "url": "https://siemens.sharepoint.com/teams/P0003139/SitePages/DE/Apps,%20Templates%20und%20Interfaces.aspx",
     "local_path": "", "description": "SharePoint Portal FSI"},
]


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class SourcesCatalog:
    def __init__(self, excel_path: Optional[Path] = None):
        if excel_path:
            self.excel_path = Path(excel_path)
        elif MOBILE_GUIDES_DIR.exists():
            legacy = MOBILE_GUIDES_DIR / "ULaE_Sources_Catalog.xlsx"
            self.excel_path = legacy if legacy.exists() else MOBILE_GUIDES_DIR / "NexusX_Sources_Catalog.xlsx"
        else:
            self.excel_path = ensure_app_dir() / "NexusX_Sources_Catalog.xlsx"
        self.json_path = SOURCES_JSON
        self.items: List[Dict[str, Any]] = []
        self.load()

    def load(self) -> None:
        try:
            from openpyxl import load_workbook
        except Exception:
            load_workbook = None
        if self.excel_path.exists() and load_workbook:
            try:
                wb = load_workbook(self.excel_path, data_only=True)
                rows = list(wb.active.iter_rows(values_only=True))
                if len(rows) > 1:
                    headers = [str(c or "").strip().lower() for c in rows[0]]
                    parsed = []
                    for idx, r in enumerate(rows[1:], 1):
                        if not any(r):
                            continue
                        d = {h: str(v or "").strip() for h, v in zip(headers, r)}
                        parsed.append({
                            "id": d.get("id") or _new_id(),
                            "name": d.get("name") or d.get("resource name") or f"Source {idx}",
                            "type": d.get("type") or "Web Resource",
                            "url": d.get("url") or d.get("sharepoint url") or "",
                            "local_path": d.get("local path") or d.get("local_path") or "",
                            "description": d.get("description") or d.get("notes") or "",
                        })
                    if parsed:
                        self.items = parsed
                        return
            except Exception:
                pass
        for jp in (self.json_path, LEGACY_ULAE_SOURCES_JSON):
            if jp.exists():
                try:
                    data = json.loads(jp.read_text(encoding="utf-8"))
                    if isinstance(data, list) and data:
                        self.items = [dict(x, id=x.get("id") or _new_id()) for x in data]
                        self.save()
                        return
                except Exception:
                    pass
        self.items = [dict(x, id=_new_id()) for x in DEFAULT_SOURCES]
        self.save()

    def save(self) -> None:
        self.save_excel()
        self.save_json()

    def save_excel(self) -> None:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
        except Exception:
            return
        try:
            self.excel_path.parent.mkdir(parents=True, exist_ok=True)
            wb = Workbook()
            ws = wb.active
            ws.title = "NexusX Sources"
            headers = ["Name", "Type", "URL", "Local Path", "Description", "Id"]
            ws.append(headers)
            for c in range(1, len(headers) + 1):
                cell = ws.cell(row=1, column=c)
                cell.font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="006487", end_color="006487", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center")
            for it in self.items:
                ws.append([it.get("name", ""), it.get("type", ""), it.get("url", ""), it.get("local_path", ""),
                           it.get("description", ""), it.get("id", "")])
            for col, w in zip("ABCDEF", (30, 18, 65, 65, 35, 10)):
                ws.column_dimensions[col].width = w
            ws.freeze_panes = "A2"
            wb.save(self.excel_path)
        except Exception:
            pass

    def save_json(self) -> None:
        try:
            ensure_app_dir()
            self.json_path.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add_or_update(self, item: Dict[str, Any]) -> None:
        existing = next((x for x in self.items if item.get("id") and x.get("id") == item.get("id")), None)
        if existing is None and item.get("url"):
            existing = next((x for x in self.items if x.get("url") and x.get("url") == item.get("url")), None)
        if existing:
            existing.update(item)
        else:
            item.setdefault("id", _new_id())
            if not item["id"]:
                item["id"] = _new_id()
            self.items.append(item)
        self.save()

    def delete(self, item_id: str) -> None:
        self.items = [x for x in self.items if x.get("id") != item_id]
        self.save()

    def open_excel_file(self) -> None:
        self.save_excel()
        if self.excel_path.exists():
            if sys.platform == "win32":
                os.startfile(str(self.excel_path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(self.excel_path)])

    def resolve_local_file(self, url: str) -> Optional[Path]:
        """Map a SharePoint/OneDrive web URL to a locally synced file."""
        if not url:
            return None
        clean = url.split("?")[0].lower()
        for it in self.items:
            if (it.get("url") or "").split("?")[0].lower() == clean and it.get("local_path"):
                lp = Path(it["local_path"])
                if lp.exists():
                    return lp
                cand = DOCS_DIR / lp.name
                if cand.exists():
                    return cand
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query)
        fname = Path(urllib.parse.unquote(parsed.path)).name
        for key in ("file", "File"):
            if q.get(key):
                fname = q[key][0]
        if fname.lower().endswith(".aspx") and q.get("id"):
            fname = Path(urllib.parse.unquote(q["id"][0])).name
        if not fname or len(fname) < 4 or fname.lower().endswith(".aspx"):
            return None
        dirs = [DOCS_DIR, MOBILE_GUIDES_DIR, SIEMENS_ONEDRIVE / "__myCreativity" / "UCeX" / "ULaE__Siemens"]
        for d in dirs:
            if d.exists():
                c = d / fname
                if c.exists():
                    return c
                for child in d.iterdir():
                    if child.is_file() and (child.name.lower() == fname.lower() or fname.lower() in child.name.lower()):
                        return child
        if SIEMENS_ONEDRIVE.exists():  # last resort: bounded search in the synced tree
            try:
                for i, p in enumerate(SIEMENS_ONEDRIVE.rglob(fname)):
                    return p
            except Exception:
                pass
        return None
