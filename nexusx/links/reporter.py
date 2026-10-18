# -*- coding: utf-8 -*-
"""
Link audit reports (ULaE v2.0 exporter.py) — same 5 formats + HTML, improved:
  • Excel: status-coloured rows, clickable links, column widths, Summary sheet, filters
  • Word: summary table + one results table per source document (instead of 6 paragraphs per link)
  • Markdown: summary + table incl. section (§) and notes
  • HTML: standalone, filterable report
"""
from __future__ import annotations

import csv
import datetime
import html
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List

from .. import APP_NAME, APP_VERSION
from .models import LinkRecord, status_group

FIELDS = ["file", "location", "section", "url", "status", "http_code", "final_url", "evidence",
          "download_status", "download_filename", "download_size", "anchor", "context", "source",
          "target_section", "response_ms", "occurrences", "parent_url", "notes", "error", "checked_at"]

GROUP_COLORS = {  # (font, fill)
    "ok": ("107C41", "E6F4EA"),
    "broken": ("A80000", "FDE7E9"),
    "auth": ("B05A00", "FFF4CE"),
    "download": ("005A9E", "E1EFFA"),
    "warn": ("7A5C00", "FFF8DC"),
    "pending": ("605E5C", "F3F2F1"),
}
REPORT_STEM = "NexusX_Link_Audit"


def summarize(records: List[LinkRecord]) -> Dict[str, int]:
    c = Counter(status_group(r.status) for r in records)
    return {"total": len(records), "ok": c["ok"], "broken": c["broken"], "auth": c["auth"],
            "download": c["download"], "warn": c["warn"], "pending": c["pending"]}


def _flat(v) -> str:
    if isinstance(v, list):
        return "; ".join(str(i) for i in v)
    return "" if v is None else str(v)


def export_records(records: List[LinkRecord], out_path: Path, fmt: str) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt == ".json":
        out_path.write_text(json.dumps({"tool": f"{APP_NAME} v{APP_VERSION}",
                                        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
                                        "summary": summarize(records),
                                        "records": [r.to_dict() for r in records]}, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    elif fmt == ".csv":
        with out_path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in records:
                d = r.to_dict()
                w.writerow({k: _flat(d.get(k, "")) for k in FIELDS})
    elif fmt == ".xlsx":
        _xlsx(records, out_path)
    elif fmt == ".md":
        _md(records, out_path)
    elif fmt == ".docx":
        _docx(records, out_path)
    elif fmt == ".html":
        out_path.write_text(to_html(records), encoding="utf-8")
    else:
        raise ValueError(f"Unsupported format {fmt}")
    return out_path


def _xlsx(records: List[LinkRecord], out_path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Link Audit"
    headers = [f.replace("_", " ").capitalize() for f in FIELDS]
    ws.append(headers)
    hfont = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    hfill = PatternFill(start_color="006487", end_color="006487", fill_type="solid")
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font, cell.fill = hfont, hfill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    url_col = FIELDS.index("url") + 1
    status_col = FIELDS.index("status") + 1
    for i, r in enumerate(records, 2):
        d = r.to_dict()
        ws.append([_flat(d.get(k, ""))[:32000] for k in FIELDS])
        font_c, fill_c = GROUP_COLORS.get(status_group(r.status), GROUP_COLORS["pending"])
        sc = ws.cell(row=i, column=status_col)
        sc.font = Font(bold=True, color=font_c)
        sc.fill = PatternFill(start_color=fill_c, end_color=fill_c, fill_type="solid")
        if r.url.lower().startswith(("http", "mailto:", "file:")):
            uc = ws.cell(row=i, column=url_col)
            try:
                uc.hyperlink = r.final_url or r.url
                uc.font = Font(color="006487", underline="single")
            except Exception:
                pass
    widths = {"file": 28, "location": 30, "section": 30, "url": 60, "status": 22, "http_code": 9,
              "final_url": 45, "evidence": 50, "notes": 30, "error": 40, "context": 50, "anchor": 30}
    for idx, f in enumerate(FIELDS, 1):
        ws.column_dimensions[get_column_letter(idx)].width = widths.get(f, 16)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    s = wb.create_sheet("Summary", 0)
    summ = summarize(records)
    s.append([f"{APP_NAME} Link Audit", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")])
    s["A1"].font = Font(size=14, bold=True, color="006487")
    s.append([])
    for label, key in (("Total", "total"), ("OK", "ok"), ("Broken / Error", "broken"), ("Auth required", "auth"),
                       ("Downloads", "download"), ("Warnings", "warn"), ("Not checked", "pending")):
        s.append([label, summ[key]])
    s.append([])
    s.append(["Per file", "Total", "Broken", "Auth"])
    per: Dict[str, Counter] = {}
    for r in records:
        per.setdefault(r.file, Counter())[status_group(r.status)] += 1
    for f, c in sorted(per.items()):
        s.append([f, sum(c.values()), c["broken"], c["auth"]])
    s.column_dimensions["A"].width = 50
    wb.save(out_path)


def _md(records: List[LinkRecord], out_path: Path) -> None:
    s = summarize(records)
    lines = [f"# {APP_NAME} Link Audit Report",
             f"*Generated on {datetime.datetime.now():%Y-%m-%d %H:%M:%S}*", "",
             f"**Total:** {s['total']} · ✓ {s['ok']} · ✗ {s['broken']} · ⚠ Auth {s['auth']} · ⬇ {s['download']} · ? {s['warn'] + s['pending']}",
             "", "| # | File | Location | § Section | URL | Status | HTTP | Evidence / Notes |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(records, 1):
        ev = (r.evidence or r.error or "").replace("|", "/").replace("\n", " ")[:120]
        url = r.url.replace("|", "%7C")
        link = f"[{url}]({url})" if not url.startswith("#") else f"`{url}`"
        note = f" · **Note:** {r.notes}" if r.notes else ""
        lines.append(f"| {i} | {r.file} | {r.location[:80]} | {r.section[:50]} | {link} | **{r.status}** | {r.http_code} | {ev}{note} |")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _docx(records: List[LinkRecord], out_path: Path) -> None:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    doc.add_heading(f"{APP_NAME} Link Audit Report", 0)
    s = summarize(records)
    doc.add_paragraph(f"Generated on: {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · Total links: {s['total']}")
    t = doc.add_table(rows=1, cols=6)
    t.style = "Light Grid Accent 1"
    for c, h in enumerate(("OK", "Broken / Error", "Auth required", "Downloads", "Warnings", "Not checked")):
        t.rows[0].cells[c].text = h
    row = t.add_row().cells
    for c, k in enumerate(("ok", "broken", "auth", "download", "warn", "pending")):
        row[c].text = str(s[k])

    def shade(cell, hex_fill):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_fill)
        tcPr.append(shd)

    by_file: Dict[str, List[LinkRecord]] = {}
    for r in records:
        by_file.setdefault(r.file, []).append(r)
    for fname, recs in by_file.items():
        doc.add_heading(fname, level=1)
        tbl = doc.add_table(rows=1, cols=6)
        tbl.style = "Table Grid"
        for c, h in enumerate(("Location / § Section", "Link", "Status", "HTTP", "Evidence / Error", "Notes")):
            cell = tbl.rows[0].cells[c]
            cell.text = h
            cell.paragraphs[0].runs[0].font.bold = True
            shade(cell, "006487")
            cell.paragraphs[0].runs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        for r in recs:
            cells = tbl.add_row().cells
            cells[0].text = r.location[:200] + (f"\n§ {r.section}" if r.section else "")
            cells[1].text = r.url
            cells[2].text = r.status
            cells[3].text = r.http_code
            cells[4].text = (r.evidence or "")[:300] + (f"\n{r.error}" if r.error else "")
            cells[5].text = r.notes or ""
            font_c, fill_c = GROUP_COLORS.get(status_group(r.status), GROUP_COLORS["pending"])
            shade(cells[2], fill_c)
            for p in cells[2].paragraphs:
                for run in p.runs:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor.from_string(font_c)
            for c in cells:
                for p in c.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(8)
    doc.save(out_path)


def to_html(records: List[LinkRecord]) -> str:
    e = html.escape
    s = summarize(records)
    rows = []
    for i, r in enumerate(records, 1):
        g = status_group(r.status)
        fc, bc = GROUP_COLORS.get(g, GROUP_COLORS["pending"])
        href = e(r.final_url or r.url)
        rows.append(f"<tr data-g='{g}'><td>{i}</td><td>{e(r.file)}</td><td>{e(r.location[:120])}<br><small>{e(r.section)}</small></td>"
                    f"<td class='u'><a href='{href}'>{e(r.url)}</a></td>"
                    f"<td><span style='color:#{fc};background:#{bc};padding:2px 6px;border-radius:4px;font-weight:600'>{e(r.status)}</span></td>"
                    f"<td>{e(r.http_code)}</td><td>{e((r.evidence or r.error)[:200])}</td><td>{e(r.notes)}</td></tr>")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{APP_NAME} Link Audit</title>
<style>body{{font-family:"Segoe UI",Arial,sans-serif;margin:20px;color:#212529}} h1{{color:#006487}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th{{background:#006487;color:#fff;padding:8px;position:sticky;top:0}}
td{{border-bottom:1px solid #e1dfdd;padding:6px;vertical-align:top}} td.u{{word-break:break-all}} .b{{margin:6px 0 14px}}
button{{margin-right:6px;padding:4px 10px;border:1px solid #006487;background:#fff;color:#006487;border-radius:4px;cursor:pointer}}</style></head><body>
<h1>{APP_NAME} Link Audit</h1><p>{datetime.datetime.now():%Y-%m-%d %H:%M} · Total {s['total']} · ✓ {s['ok']} · ✗ {s['broken']} · ⚠ {s['auth']} · ⬇ {s['download']}</p>
<div class="b"><button onclick="f('')">Toate</button><button onclick="f('broken')">Erori</button><button onclick="f('auth')">Auth</button><button onclick="f('ok')">OK</button><button onclick="f('warn')">Avertizari</button></div>
<table><tr><th>#</th><th>Fisier</th><th>Locatie / §</th><th>Link</th><th>Status</th><th>HTTP</th><th>Dovada</th><th>Note</th></tr>{''.join(rows)}</table>
<script>function f(g){{document.querySelectorAll('tr[data-g]').forEach(function(r){{r.style.display=(!g||r.dataset.g==g)?'':'none';}});}}</script>
</body></html>"""


def export_all(records: List[LinkRecord], out_dir: Path, stem: str = REPORT_STEM,
               formats=(".xlsx", ".docx", ".csv", ".md", ".json")) -> List[Path]:
    out = []
    for ext in formats:
        try:
            out.append(export_records(records, Path(out_dir) / f"{stem}{ext}", ext))
        except Exception:
            continue
    return out
