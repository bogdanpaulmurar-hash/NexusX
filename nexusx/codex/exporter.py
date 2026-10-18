# -*- coding: utf-8 -*-
"""
Code export writer (UCeX v6.7 _write_export_file + _write_export_split), unified and improved:
  • one renderer for split and non-split (v6.7 had two diverging copies — e.g. line numbers
    were forced on in split .txt and MD5 was always computed there)
  • exact "Parte N/M" in every part header (v6.7 printed "(estimat...)")
  • TOC also for .md/.html (clickable in HTML), extension statistics ("Stats" option was unused)
  • JSON split by real serialized size (v6.7 extrapolated from the first file only)
  • secret redaction, binary skipping, optional Link Map appendix, cooperative stop
"""
from __future__ import annotations

import datetime
import html
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .. import APP_NAME, APP_VERSION
from .constants import detect_lang
from .redact import redact
from .scanner import is_binary, md5_file, read_text

MB = 1024 * 1024
FORMATS = (".txt", ".md", ".html", ".json")


@dataclass
class ExportSettings:
    header: bool = True
    toc: bool = True
    stats: bool = True
    md5: bool = True
    line_numbers: bool = False
    compress_ws: bool = False
    redact: bool = True
    include_binary: bool = False
    split_bytes: Optional[int] = None
    appendix_md: str = ""          # e.g. Link Map in Markdown, appended to the last part


@dataclass
class ExportResult:
    parts: List[Path] = field(default_factory=list)
    files_written: int = 0
    skipped_binary: List[str] = field(default_factory=list)
    redactions: int = 0
    total_bytes: int = 0


def split_bytes_for(mode: str, custom_mb: str = "50") -> Optional[int]:
    """Map the UCeX split radio values ('none','50mb','99mb','custom') to bytes."""
    if mode == "50mb":
        return 50 * MB
    if mode == "99mb":
        return 99 * MB
    if mode == "custom":
        try:
            return max(1, int(float(str(custom_mb).replace(",", ".")) * MB))
        except Exception:
            return 50 * MB
    return None


class _Renderer:
    def __init__(self, fmt: str, files: List[Path], root: Path, label: str, st: ExportSettings):
        self.fmt = fmt
        self.files = files
        self.root = root
        self.label = label or root.name
        self.st = st
        self.now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.redactions = 0
        self.skipped: List[str] = []
        self._binary_cache: Dict[Path, bool] = {}

    # helpers
    def rel(self, fp: Path) -> str:
        try:
            return str(fp.relative_to(self.root))
        except ValueError:
            return str(fp)

    def binary(self, fp: Path) -> bool:
        if fp not in self._binary_cache:
            self._binary_cache[fp] = is_binary(fp)
        return self._binary_cache[fp]

    def content(self, fp: Path, count: bool) -> str:
        if self.binary(fp):
            return "<binary file — content not exported>"
        try:
            text = read_text(fp)
        except Exception as e:  # noqa: BLE001
            return f"<unreadable: {e}>"
        if self.st.compress_ws:
            text = re.sub(r"\n{3,}", "\n\n", text)
        if self.st.redact:
            text, n = redact(text)
            if count:
                self.redactions += n
        return text

    # sections
    def header(self, part: int, total_parts: int) -> str:
        if not self.st.header:
            if self.fmt == ".html":
                return self._html_head(part, total_parts, minimal=True)
            return ""
        part_txt = f"{part}/{total_parts}"
        f = self.fmt
        if f == ".txt":
            return ("=" * 70 + "\n"
                    f" {APP_NAME} v{APP_VERSION} — {self.label}\n"
                    f" Data     : {self.now}\n"
                    f" Sursa    : {self.root}\n"
                    f" Fisiere  : {len(self.files)}\n"
                    f" Parte    : {part_txt}\n"
                    f" Redactare: {'ON' if self.st.redact else 'OFF'}\n"
                    f" Politica : SiemensGPT ACP-2 compliant\n"
                    + "=" * 70 + "\n\n")
        if f == ".md":
            return (f"# {APP_NAME} v{APP_VERSION} — {self.label}\n\n"
                    "| Camp | Valoare |\n|---|---|\n"
                    f"| Data | `{self.now}` |\n| Sursa | `{self.root}` |\n"
                    f"| Fisiere | `{len(self.files)}` |\n| Parte | `{part_txt}` |\n"
                    f"| Redactare secrete | `{'ON' if self.st.redact else 'OFF'}` |\n\n---\n\n")
        if f == ".html":
            return self._html_head(part, total_parts)
        return ""

    def _html_head(self, part: int, total: int, minimal: bool = False) -> str:
        e = html.escape
        h = ('<!DOCTYPE html><html lang="ro"><head><meta charset="UTF-8">'
             f'<title>{APP_NAME} Export — {e(self.label)} — {part}/{total}</title><style>'
             'body{background:#1c1f26;color:#e8edf3;font-family:"Segoe UI",Arial,sans-serif;padding:20px;max-width:1400px;margin:auto}'
             'h1{color:#00c2de} h2{color:#7dd3fc;margin-top:2em;border-bottom:1px solid #3a4050;padding-bottom:4px}'
             'pre{background:#262a34;padding:16px;border-radius:6px;overflow-x:auto;white-space:pre-wrap;font-family:Consolas,"Courier New",monospace;font-size:13px}'
             'a{color:#38bdf8} small{color:#a3b0c2} table{border-collapse:collapse} td,th{border:1px solid #3a4050;padding:4px 10px}'
             'th{background:#2a2f3a;color:#00c2de}</style></head><body>\n')
        if not minimal:
            h += (f"<h1>{APP_NAME} v{APP_VERSION} — {e(self.label)} — Parte {part}/{total}</h1>\n"
                  f"<p>Data: {self.now} | Sursa: {e(str(self.root))} | Fisiere: {len(self.files)}"
                  f" | Redactare: {'ON' if self.st.redact else 'OFF'}</p>\n")
        return h

    def toc(self, assignment: Dict[int, int], only_part: Optional[int] = None) -> str:
        if not self.st.toc:
            return ""
        rows = [(i, fp) for i, fp in enumerate(self.files, 1)
                if only_part is None or assignment.get(i) == only_part]
        multi = len(set(assignment.values())) > 1
        f = self.fmt
        buf = io.StringIO()
        if f == ".txt":
            buf.write("TABLE OF CONTENTS\n" + "-" * 40 + "\n")
            for i, fp in rows:
                suffix = f"   [part {assignment[i]}]" if multi else ""
                buf.write(f" {i:>4}. {self.rel(fp)}{suffix}\n")
            buf.write("\n")
        elif f == ".md":
            buf.write("## Cuprins\n\n")
            for i, fp in rows:
                suffix = f" _(partea {assignment[i]})_" if multi else ""
                buf.write(f"{i}. `{self.rel(fp)}`{suffix}\n")
            buf.write("\n---\n\n")
        elif f == ".html":
            buf.write("<h2>Cuprins</h2><ol>\n")
            for i, fp in rows:
                same = (only_part is None) or assignment.get(i) == only_part
                target = f'#f{i}' if same else ''
                suffix = f" <small>(partea {assignment[i]})</small>" if multi else ""
                buf.write(f'<li><a href="{target}">{html.escape(self.rel(fp))}</a>{suffix}</li>\n')
            buf.write("</ol>\n")
        return buf.getvalue()

    def stats(self) -> str:
        if not self.st.stats:
            return ""
        cnt: Counter = Counter()
        size_by: Counter = Counter()
        total = 0
        for fp in self.files:
            k = fp.suffix.lower() or fp.name.lower()
            try:
                sz = fp.stat().st_size
            except OSError:
                sz = 0
            cnt[k] += 1
            size_by[k] += sz
            total += sz
        top = cnt.most_common(25)
        f = self.fmt
        if f == ".txt":
            s = "STATISTICI\n" + "-" * 40 + "\n"
            s += f" Total fisiere: {len(self.files)} | Marime: {total / MB:.2f} MB\n"
            for k, n in top:
                s += f" {k:<20} {n:>6} fisiere  {size_by[k] / 1024:>10.1f} KB\n"
            return s + "\n"
        if f == ".md":
            s = f"## Statistici\n\nTotal fisiere: **{len(self.files)}** · Marime: **{total / MB:.2f} MB**\n\n"
            s += "| Extensie | Fisiere | KB |\n|---|---:|---:|\n"
            for k, n in top:
                s += f"| `{k}` | {n} | {size_by[k] / 1024:.1f} |\n"
            return s + "\n"
        if f == ".html":
            s = f"<h2>Statistici</h2><p>Total fisiere: <b>{len(self.files)}</b> · Marime: <b>{total / MB:.2f} MB</b></p>"
            s += "<table><tr><th>Extensie</th><th>Fisiere</th><th>KB</th></tr>"
            for k, n in top:
                s += f"<tr><td>{html.escape(k)}</td><td>{n}</td><td>{size_by[k] / 1024:.1f}</td></tr>"
            return s + "</table>\n"
        return ""

    def block(self, fp: Path, idx: int, count: bool) -> str:
        rel = self.rel(fp)
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        lang = detect_lang(fp)
        md5 = md5_file(fp) if self.st.md5 else ""
        content = self.content(fp, count)
        n = len(self.files)
        f = self.fmt
        if f == ".txt":
            meta = f"SIZE: {size / 1024:.1f} KB | LANG: {lang}" + (f" | MD5: {md5}" if md5 else "")
            body = (
                "".join(f"{i:>4} | {line}\n" for i, line in enumerate(content.splitlines(), 1))
                if self.st.line_numbers else content + ("" if content.endswith("\n") else "\n")
            )
            return ("=" * 70 + "\n" f"FILE [{idx}/{n}]: {rel}\n{meta}\n" + "=" * 70 + "\n" + body + "\n")
        if f == ".md":
            fence = "````" if "```" in content else "```"
            meta = f"*[{idx}/{n}] Size: {size / 1024:.1f} KB" + (f" | MD5: `{md5}`" if md5 else "") + "*"
            if self.st.line_numbers:
                content = "\n".join(f"{i:>4} | {l}" for i, l in enumerate(content.splitlines(), 1))
            return f"## `{rel}`\n\n{meta}\n\n{fence}{lang}\n{content}\n{fence}\n\n"
        if f == ".html":
            meta = f"[{idx}/{n}] Size: {size / 1024:.1f} KB" + (f" | MD5: {md5}" if md5 else "")
            if self.st.line_numbers:
                content = "\n".join(f"{i:>4} | {l}" for i, l in enumerate(content.splitlines(), 1))
            return (f'<h2 id="f{idx}">{html.escape(rel)}</h2>\n<p><small>{meta}</small></p>\n'
                    f'<pre><code class="{lang}">{html.escape(content)}</code></pre>\n')
        return ""

    def footer(self, part: int, total: int, next_name: Optional[str]) -> str:
        f = self.fmt
        appendix = ""
        if next_name is None and self.st.appendix_md:
            if f == ".html":
                appendix = f"<h2>Link Map</h2><pre>{html.escape(self.st.appendix_md)}</pre>\n"
            else:
                appendix = "\n" + self.st.appendix_md.rstrip() + "\n"
        if f == ".txt":
            msg = (f" *** END PART {part}/{total} — CONTINUA CU: {next_name} ***" if next_name
                   else f" *** END PART {part}/{total} — EXPORT COMPLET ***")
            return appendix + "\n" + "=" * 70 + "\n" + msg + "\n" + "=" * 70 + "\n"
        if f == ".md":
            msg = (f"> **END PART {part}/{total}** — Continua cu: `{next_name}`" if next_name
                   else f"> **END PART {part}/{total}** — Export complet.")
            return appendix + "\n---\n\n" + msg + "\n"
        if f == ".html":
            msg = (f"<strong>END PART {part}/{total}</strong> — Continua cu: <code>{html.escape(next_name)}</code>"
                   if next_name else f"<strong>END PART {part}/{total}</strong> — Export complet.")
            return appendix + f"<hr><p>{msg}</p>\n</body></html>\n"
        return ""


def export_files(out_path: Path, fmt: str, files: List[Path], root: Path, label: str = "",
                 settings: Optional[ExportSettings] = None,
                 progress: Optional[Callable[[int, int], None]] = None,
                 stop: Optional[Callable[[], bool]] = None) -> ExportResult:
    """Write the export (optionally split). Returns the written parts and statistics."""
    st = settings or ExportSettings()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(root)
    fmt = fmt if fmt in FORMATS else ".txt"

    r = _Renderer(fmt, list(files), root, label, st)
    if not st.include_binary:
        kept = []
        for fp in r.files:
            if r.binary(fp):
                r.skipped.append(r.rel(fp))
            else:
                kept.append(fp)
        r.files = kept

    res = ExportResult(skipped_binary=r.skipped)
    if fmt == ".json":
        res.parts = _export_json(out_path, r, st, progress, stop)
    else:
        res.parts = _export_text(out_path, r, st, progress, stop)
    res.files_written = len(r.files)
    res.redactions = r.redactions
    res.total_bytes = sum(p.stat().st_size for p in res.parts if p.exists())
    return res


def _part_path(out_path: Path, n: int) -> Path:
    return out_path.parent / f"{out_path.stem}_part{n}{out_path.suffix}"


def _export_text(out_path: Path, r: _Renderer, st: ExportSettings, progress, stop) -> List[Path]:
    n = len(r.files)
    assignment: Dict[int, int] = {}
    if st.split_bytes:
        # pass 1: measure blocks and assign files to parts
        overhead = len((r.header(1, 99) + r.footer(1, 99, "x" * 40)).encode("utf-8")) + 4096
        part, size = 1, overhead
        for i, fp in enumerate(r.files, 1):
            if stop and stop():
                break
            b = len(r.block(fp, i, count=False).encode("utf-8"))
            if size + b > st.split_bytes and size > overhead:
                part += 1
                size = overhead
            size += b
            assignment[i] = part
            if progress:
                progress(i, n * 2)
    else:
        assignment = {i: 1 for i in range(1, n + 1)}
    total_parts = max(assignment.values()) if assignment else 1
    paths = [out_path] if total_parts == 1 else [_part_path(out_path, p) for p in range(1, total_parts + 1)]

    done = 0
    for p_idx, path in enumerate(paths, 1):
        with open(path, "w", encoding="utf-8", errors="replace", newline="\n") as fh:
            fh.write(r.header(p_idx, total_parts))
            if p_idx == 1:
                fh.write(r.stats())
                fh.write(r.toc(assignment))
            elif r.st.toc:
                fh.write(r.toc(assignment, only_part=p_idx))
            for i, fp in enumerate(r.files, 1):
                if assignment.get(i) != p_idx:
                    continue
                if stop and stop():
                    break
                fh.write(r.block(fp, i, count=True))
                done += 1
                if progress:
                    progress((n if st.split_bytes else 0) + done, n * (2 if st.split_bytes else 1))
            nxt = paths[p_idx].name if p_idx < total_parts else None
            fh.write(r.footer(p_idx, total_parts, nxt))
    return paths


def _export_json(out_path: Path, r: _Renderer, st: ExportSettings, progress, stop) -> List[Path]:
    n = len(r.files)
    meta = {"tool": f"{APP_NAME} v{APP_VERSION}", "date": r.now, "source": str(r.root),
            "files": n, "label": r.label, "redacted": st.redact}
    entries = []
    for i, fp in enumerate(r.files, 1):
        if stop and stop():
            break
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        entries.append({"path": r.rel(fp), "ext": fp.suffix, "size": size,
                        "md5": md5_file(fp) if st.md5 else "", "lang": detect_lang(fp),
                        "content": r.content(fp, count=True)})
        if progress:
            progress(i, n)
    chunks: List[List[dict]] = []
    if st.split_bytes:
        cur, cur_size = [], 2048
        for e in entries:
            sz = len(json.dumps(e, ensure_ascii=False, indent=2).encode("utf-8")) + 4
            if cur and cur_size + sz > st.split_bytes:
                chunks.append(cur)
                cur, cur_size = [], 2048
            cur.append(e)
            cur_size += sz
        chunks.append(cur)
    else:
        chunks = [entries]
    total = len(chunks)
    paths = [out_path] if total == 1 else [_part_path(out_path, p) for p in range(1, total + 1)]
    for idx, (path, chunk) in enumerate(zip(paths, chunks), 1):
        doc = {"meta": dict(meta, part=idx, parts=total, files_in_part=len(chunk)), "files": chunk}
        if idx == total and r.skipped:
            doc["skipped_binary"] = r.skipped
        if idx == total and st.appendix_md:
            doc["link_map_md"] = st.appendix_md
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
    return paths


def zip_parts(parts: List[Path], zip_path: Path) -> Path:
    """Zip ALL parts (UCeX v6.7 zipped only the first/unsplit file)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in parts:
            zf.write(p, p.name)
    return zip_path


def estimate(files: List[Path]) -> str:
    """Human estimate + split preview (UCeX 'Dimensiune estimata')."""
    total = 0
    for fp in files:
        try:
            total += fp.stat().st_size
        except OSError:
            pass
    size_str = f"{total / 1024:.1f} KB" if total < MB else f"{total / MB:.2f} MB"
    p50 = max(1, -(-total // (50 * MB)))
    p99 = max(1, -(-total // (99 * MB)))
    word = lambda k: "parte" if k == 1 else "parti"  # noqa: E731
    return f"{len(files)} fisiere · ~{size_str} | split 50MB → {p50} {word(p50)} | 99MB → {p99} {word(p99)}"
