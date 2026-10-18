# -*- coding: utf-8 -*-
"""
"Rezumat Folder" (UCeX v6.7 _summary_thread), ported and fixed:
  • images section now also in .html/.json and with pixel size when Pillow is present
  • binary-file info section (option existed in v6.7 but was ignored)
  • secret redaction and binary skipping for the code section
  • excluded folders honoured in stats/code (v6.7 counted node_modules, .git …)
"""
from __future__ import annotations

import datetime
import html
import json
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .. import APP_NAME, APP_VERSION
from .constants import ALL_EXTS, DEFAULT_EXCLUDED, IMAGE_EXTS, detect_lang, matches_exts
from .redact import redact
from .scanner import is_binary, md5_file, read_text

SUMMARY_OPTIONS = {
    "tree": "🌲 Arbore director (tree)",
    "stats": "📊 Statistici globale (nr fisiere, marime, extensii)",
    "code": "💻 Continut cod sursa",
    "images": "🖼️ Info imagini (format, dimensiune, rezolutie)",
    "md5": "🔑 Hash MD5 per fisier",
    "git": "📜 Git log (daca exista repo)",
    "binary": "📦 Include fisiere binare (info)",
    "hidden": "👁️ Include fisiere ascunse",
}
SUMMARY_DEFAULTS = {"tree": True, "stats": True, "code": True, "images": True, "md5": True,
                    "git": True, "binary": False, "hidden": False}


def _iter_files(root: Path, hidden: bool):
    excl = set(DEFAULT_EXCLUDED.split(","))
    for fp in root.rglob("*"):
        try:
            rel_parts = fp.relative_to(root).parts
        except ValueError:
            continue
        if any(p in excl for p in rel_parts[:-1]):
            continue
        if not hidden and any(p.startswith(".") for p in rel_parts):
            continue
        if fp.is_file():
            yield fp


def _image_info(fp: Path) -> str:
    try:
        from PIL import Image  # type: ignore
        with Image.open(fp) as im:
            return f"{im.width}x{im.height} {im.mode}"
    except Exception:
        return ""


def build_summary(root: Path, out_path: Path, fmt: str, opts: Dict[str, bool],
                  redact_secrets: bool = True, max_code_files: int = 200,
                  log: Optional[Callable[[str], None]] = None) -> Path:
    root = Path(root)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    o = dict(SUMMARY_DEFAULTS, **opts)
    e = html.escape
    lines: List[str] = []
    data: Dict = {"meta": {"tool": f"{APP_NAME} v{APP_VERSION}", "date": now, "folder": str(root),
                           "name": root.name}, "sections": {}}
    files = list(_iter_files(root, o["hidden"]))

    if fmt == ".md":
        lines.append(f"# 📋 Rezumat Folder: `{root.name}`\n\n**Generat:** {now}  \n**Cale:** `{root}`  \n"
                     f"**Tool:** {APP_NAME} v{APP_VERSION}\n\n---\n\n")
    elif fmt == ".txt":
        lines.append("=" * 70 + f"\n REZUMAT FOLDER: {root.name}\n Data: {now}\n Cale: {root}\n" + "=" * 70 + "\n\n")
    elif fmt == ".html":
        lines.append('<!DOCTYPE html><html lang="ro"><head><meta charset="UTF-8">'
                     f'<title>Rezumat {e(root.name)}</title><style>'
                     'body{background:#1c1f26;color:#e8edf3;font-family:"Segoe UI",sans-serif;padding:20px}'
                     'h1,h2{color:#00c2de} pre{background:#262a34;padding:12px;border-radius:6px;overflow-x:auto}'
                     'table{border-collapse:collapse} td,th{border:1px solid #3a4050;padding:6px 10px}'
                     'th{background:#2a2f3a;color:#7dd3fc}</style></head><body>'
                     f'<h1>Rezumat: {e(root.name)}</h1><p>Generat: {now} | Cale: {e(str(root))}</p>')

    # ── tree ──
    if o["tree"]:
        tree_lines: List[str] = []
        excl = set(DEFAULT_EXCLUDED.split(","))

        def walk(path: Path, prefix: str = "", depth: int = 0):
            if depth > 6:
                return
            try:
                items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            except Exception:
                return
            items = [i for i in items if o["hidden"] or not i.name.startswith(".")]
            for i, item in enumerate(items):
                last = i == len(items) - 1
                tree_lines.append(f"{prefix}{'└── ' if last else '├── '}{item.name}")
                if item.is_dir() and item.name not in excl:
                    walk(item, prefix + ("    " if last else "│   "), depth + 1)

        walk(root)
        if fmt == ".md":
            lines.append("## 🌲 Arbore Director\n\n```\n" + root.name + "\n" + "\n".join(tree_lines) + "\n```\n\n")
        elif fmt == ".txt":
            lines.append("─── ARBORE DIRECTOR " + "─" * 45 + "\n" + root.name + "\n" + "\n".join(tree_lines) + "\n\n")
        elif fmt == ".html":
            lines.append("<h2>Arbore Director</h2><pre>" + e(root.name + "\n" + "\n".join(tree_lines)) + "</pre>")
        else:
            data["sections"]["tree"] = [root.name] + tree_lines

    # ── stats ──
    if o["stats"]:
        ext_counts: Dict[str, int] = {}
        total = 0
        for fp in files:
            try:
                total += fp.stat().st_size
            except OSError:
                pass
            k = fp.suffix.lower() or "(none)"
            ext_counts[k] = ext_counts.get(k, 0) + 1
        top = sorted(ext_counts.items(), key=lambda x: -x[1])[:20]
        if fmt == ".md":
            lines.append("## 📊 Statistici\n\n| Camp | Valoare |\n|---|---|\n"
                         f"| Total fisiere | {len(files)} |\n| Marime totala | {total / 1048576:.2f} MB |\n"
                         f"| Tipuri distincte | {len(ext_counts)} |\n\n### Top extensii\n| Extensie | Nr. fisiere |\n|---|---|\n")
            lines += [f"| `{k}` | {c} |\n" for k, c in top]
            lines.append("\n")
        elif fmt == ".txt":
            lines.append("─── STATISTICI " + "─" * 50 + f"\n Total fisiere   : {len(files)}\n"
                         f" Marime totala   : {total / 1048576:.2f} MB\n Tipuri distincte: {len(ext_counts)}\n Top extensii:\n")
            lines += [f"   {k:<20} {c}\n" for k, c in top]
            lines.append("\n")
        elif fmt == ".html":
            lines.append(f"<h2>Statistici</h2><p>Total fisiere: <b>{len(files)}</b> | Marime: <b>{total / 1048576:.2f} MB</b></p>"
                         "<table><tr><th>Extensie</th><th>Nr. fisiere</th></tr>"
                         + "".join(f"<tr><td>{e(k)}</td><td>{c}</td></tr>" for k, c in top) + "</table>")
        else:
            data["sections"]["stats"] = {"total_files": len(files), "total_size_mb": round(total / 1048576, 3),
                                         "ext_counts": dict(top)}

    # ── code ──
    if o["code"]:
        code_files = []
        for fp in files:
            try:
                if matches_exts(fp, set(ALL_EXTS)) and fp.stat().st_size <= 5 * 1048576 and not is_binary(fp):
                    code_files.append(fp)
            except OSError:
                pass
        shown = code_files[:max_code_files]
        hdr = f"Cod Sursa ({len(code_files)} fisiere" + (f", primele {len(shown)} incluse" if len(shown) < len(code_files) else "") + ")"
        if fmt == ".md":
            lines.append(f"## 💻 {hdr}\n\n")
        elif fmt == ".txt":
            lines.append(f"─── {hdr.upper()} " + "─" * 20 + "\n")
        elif fmt == ".html":
            lines.append(f"<h2>{e(hdr)}</h2>")
        else:
            data["sections"]["code"] = []
        for fp in shown:
            try:
                rel = str(fp.relative_to(root))
                content = read_text(fp)
                if redact_secrets:
                    content, _ = redact(content)
                lang = detect_lang(fp)
                sz = fp.stat().st_size
                m5 = md5_file(fp) if o["md5"] else ""
                if fmt == ".md":
                    fence = "````" if "```" in content else "```"
                    lines.append(f"### `{rel}`\n*{sz / 1024:.1f} KB | {lang}*" + (f" | MD5: `{m5}`" if m5 else "")
                                 + f"\n\n{fence}{lang}\n{content}\n{fence}\n\n")
                elif fmt == ".txt":
                    lines.append("=" * 70 + f"\nFILE: {rel}\n" + (f"MD5: {m5}\n" if m5 else "") + "=" * 70 + f"\n{content}\n\n")
                elif fmt == ".html":
                    lines.append(f"<h3>{e(rel)}</h3><p><small>{sz / 1024:.1f} KB | {lang}</small></p>"
                                 f"<pre><code>{e(content)}</code></pre>")
                else:
                    data["sections"]["code"].append({"path": rel, "lang": lang, "size": sz, "md5": m5, "content": content})
            except Exception:
                continue

    # ── images ──
    if o["images"]:
        imgs = [fp for fp in files if fp.suffix.lower() in IMAGE_EXTS]
        rows = []
        for fp in imgs:
            try:
                rows.append((str(fp.relative_to(root)), fp.suffix.upper().lstrip("."), fp.stat().st_size / 1024, _image_info(fp)))
            except OSError:
                pass
        if rows:
            if fmt == ".md":
                lines.append(f"## 🖼️ Imagini ({len(rows)})\n\n| Fisier | Format | Marime | Rezolutie |\n|---|---|---|---|\n")
                lines += [f"| `{r}` | {f} | {kb:.1f} KB | {i} |\n" for r, f, kb, i in rows]
                lines.append("\n")
            elif fmt == ".txt":
                lines.append(f"─── IMAGINI ({len(rows)}) " + "─" * 40 + "\n")
                lines += [f"  {r:<60} {f:<6} {kb:>8.1f} KB  {i}\n" for r, f, kb, i in rows]
                lines.append("\n")
            elif fmt == ".html":
                lines.append(f"<h2>Imagini ({len(rows)})</h2><table><tr><th>Fisier</th><th>Format</th><th>KB</th><th>Rezolutie</th></tr>"
                             + "".join(f"<tr><td>{e(r)}</td><td>{f}</td><td>{kb:.1f}</td><td>{e(i)}</td></tr>" for r, f, kb, i in rows)
                             + "</table>")
            else:
                data["sections"]["images"] = [{"path": r, "format": f, "kb": round(kb, 1), "info": i} for r, f, kb, i in rows]

    # ── binary info ──
    if o["binary"]:
        bins = [fp for fp in files if fp.suffix.lower() not in IMAGE_EXTS and is_binary(fp)]
        rows = [(str(fp.relative_to(root)), fp.stat().st_size / 1024, md5_file(fp) if o["md5"] else "") for fp in bins]
        if rows:
            if fmt == ".md":
                lines.append(f"## 📦 Fisiere binare ({len(rows)})\n\n| Fisier | KB | MD5 |\n|---|---|---|\n")
                lines += [f"| `{r}` | {kb:.1f} | `{m}` |\n" for r, kb, m in rows]
                lines.append("\n")
            elif fmt == ".txt":
                lines.append(f"─── FISIERE BINARE ({len(rows)}) " + "─" * 30 + "\n")
                lines += [f"  {r:<60} {kb:>8.1f} KB {m}\n" for r, kb, m in rows]
            elif fmt == ".html":
                lines.append(f"<h2>Fisiere binare ({len(rows)})</h2><table><tr><th>Fisier</th><th>KB</th><th>MD5</th></tr>"
                             + "".join(f"<tr><td>{e(r)}</td><td>{kb:.1f}</td><td>{m}</td></tr>" for r, kb, m in rows) + "</table>")
            else:
                data["sections"]["binary"] = [{"path": r, "kb": round(kb, 1), "md5": m} for r, kb, m in rows]

    # ── git ──
    if o["git"]:
        try:
            res = subprocess.run(["git", "-C", str(root), "log", "--oneline", "-30"], capture_output=True,
                                 text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if res.returncode == 0 and res.stdout.strip():
                gl = res.stdout.strip().split("\n")
                if fmt == ".md":
                    lines.append(f"## 📜 Git Log (ultimele {len(gl)} commits)\n\n```\n" + "\n".join(gl) + "\n```\n\n")
                elif fmt == ".txt":
                    lines.append("─── GIT LOG " + "─" * 50 + "\n" + "\n".join(gl) + "\n\n")
                elif fmt == ".html":
                    lines.append("<h2>Git Log</h2><pre>" + e("\n".join(gl)) + "</pre>")
                else:
                    data["sections"]["git_log"] = gl
        except Exception:
            pass

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == ".json":
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        if fmt == ".html":
            lines.append("</body></html>\n")
        out_path.write_text("".join(lines), encoding="utf-8", errors="replace")
    if log:
        log(f"✅ Rezumat generat: {out_path}")
    return out_path
