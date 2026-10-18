# -*- coding: utf-8 -*-
"""
Split & Merge engine (UCeX v7.0 "✂ Split & Merge" tab), GUI-independent.

Kept from v7:
  • split any file into parts by size (KB/MB/GB), strategy "equal" (N equal parts) or "size" (fixed size)
  • text/code parts get the human-readable header (FISIER MAMA, PARTE, URMATOAREA …) and
    footer "END PART N of M — CONTINUA CU: …"; binary parts are raw bytes
  • part naming  <stem>_part001of003<ext>
  • merge a list of files (custom order) into one file; text parts are cleaned of split markers

Fixed / improved:
  • text is split on line boundaries — never in the middle of a line or of a UTF-8 character
  • merge really removes the headers (v7's regex required an empty line that is never written,
    so merged text files kept every "FISIER MAMA" block) — works for v7 parts too
  • a manifest <stem>.split.json (SHA-256 of the original + part list) is written; merge verifies
    the result byte-for-byte when the manifest is present and reports missing parts
  • parts can be auto-sorted by their partNNNofMMM number; streaming I/O for multi-GB files
  • optional "exact bytes" mode (no headers even for text)
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from .. import APP_NAME, APP_VERSION

TEXT_EXTS = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml",
    ".html", ".htm", ".css", ".js", ".ts", ".py", ".cs", ".java",
    ".cpp", ".c", ".h", ".hpp", ".go", ".rs", ".rb", ".php",
    ".sh", ".bat", ".ps1", ".sql", ".ini", ".cfg", ".toml",
    ".tsx", ".jsx", ".vue", ".kt", ".swift", ".gs", ".psm1", ".tsv",
}
UNITS = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
SEP_H = "=" * 72
SEP_F = "-" * 72
PART_RE = re.compile(r"^(?P<stem>.+)_part(?P<n>\d{3,})of(?P<m>\d{3,})(?P<ext>\.[^.]*)?$")
Progress = Optional[Callable[[float, str], None]]
Log = Optional[Callable[[str, str], None]]


@dataclass
class SplitResult:
    parts: List[Path] = field(default_factory=list)
    manifest: Optional[Path] = None
    is_text: bool = False


@dataclass
class MergeResult:
    output: Optional[Path] = None
    size: int = 0
    verified: Optional[bool] = None   # None = no manifest available
    missing: List[int] = field(default_factory=list)
    message: str = ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_EXTS:
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
        head.decode("utf-8")
        return b"\x00" not in head
    except UnicodeDecodeError:
        # may be cut in the middle of a char at 64 KB — retry shorter
        try:
            head[:-4].decode("utf-8")
            return b"\x00" not in head
        except UnicodeDecodeError:
            return False
    except OSError:
        return False


def plan(file_size: int, size_val: float, unit: str, mode: str) -> tuple:
    """Return (n_parts, chunk_bytes) — same arithmetic as v7."""
    chunk = max(1, int(size_val * UNITS.get(unit, UNITS["MB"])))
    n = max(1, math.ceil(file_size / chunk))
    if mode == "equal":
        chunk = max(1, math.ceil(file_size / n))
    return n, chunk


def describe(src: Path, size_val: float, unit: str, mode: str) -> str:
    """Live info label text (v7 _sm_update_split_info)."""
    size = src.stat().st_size
    n, chunk = plan(size, size_val, unit, mode)
    mb = size / 1024 ** 2
    if mode == "equal":
        return f"Fisier: {mb:.1f} MB → {n} parti de ~{mb / n:.1f} MB fiecare"
    return f"Fisier: {mb:.1f} MB → ~{n} parti de max {size_val:g} {unit}"


def part_name(stem: str, i: int, n: int, ext: str) -> str:
    return f"{stem}_part{i:03d}of{n:03d}{ext}"


def text_header(src_name: str, src_size: int, i: int, n: int, name: str, next_name: Optional[str]) -> str:
    lines = [SEP_H,
             f" FISIER MAMA   : {src_name}",
             f" DIMENSIUNE    : {src_size / 1024 ** 2:.2f} MB",
             f" PARTE         : {i} din {n}",
             f" FISIER PARTE  : {name}",
             f" URMATOAREA    : {next_name}" if next_name else " URMATOAREA    : (aceasta este ultima parte)",
             f" DATA SPLIT    : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
             f" TOOL          : {APP_NAME} v{APP_VERSION} | ACP-2"]
    if i > 1:
        lines += [" NOTA          : Aceasta este o CONTINUARE a fisierului mama.",
                  f"                 Continutul incepe de unde s-a terminat partea {i - 1}."]
    lines.append(SEP_H)
    return "\n".join(lines) + "\n"


def text_footer(i: int, n: int, next_name: Optional[str]) -> str:
    msg = (f" END PART {i} of {n} — CONTINUA CU: {next_name}" if next_name
           else f" END PART {i} of {n} — ACEASTA ESTE ULTIMA PARTE")
    return f"\n{SEP_F}\n{msg}\n{SEP_F}\n"


def split_file(src: Path, out_dir: Path, size_val: float = 100, unit: str = "MB", mode: str = "equal",
               headers: bool = True, progress: Progress = None, log: Log = None,
               stop: Optional[Callable[[], bool]] = None) -> SplitResult:
    src, out_dir = Path(src), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    n, chunk = plan(size, size_val, unit, mode)
    text = headers and is_text_file(src)
    stem, ext = src.stem, src.suffix
    say = log or (lambda m, t="info": None)
    say(f"START SPLIT: {src.name} ({size / 1024 ** 2:.2f} MB)", "ok")
    say(f"Strategie: {mode} | Chunk: {chunk / 1024 ** 2:.2f} MB | Parti planificate: {n} | "
        f"Tip: {'TEXT (antet + taiere pe linii)' if text else 'BINAR (bytes exacti)'}", "info")
    res = SplitResult(is_text=text)
    digest = hashlib.sha256()
    bounds: List[tuple] = []
    if text:
        # compute line-aligned boundaries first so "N of M" is exact
        with open(src, "rb") as f:
            start = 0
            while start < size:
                end = min(size, start + chunk)
                if end < size:
                    f.seek(end)
                    tail = f.read(min(chunk, 1 << 20))
                    nl = tail.find(b"\n")
                    end = end + nl + 1 if nl >= 0 else min(size, end + len(tail))
                bounds.append((start, end))
                start = end
    else:
        bounds = [(i * chunk, min(size, (i + 1) * chunk)) for i in range(n)]
    n = len(bounds) or 1
    with open(src, "rb") as f_in:
        for i, (a, b) in enumerate(bounds, 1):
            if stop and stop():
                say("Split oprit de utilizator.", "warn")
                break
            name = part_name(stem, i, n, ext)
            nxt = part_name(stem, i + 1, n, ext) if i < n else None
            p = out_dir / name
            f_in.seek(a)
            remaining = b - a
            with open(p, "wb") as f_out:
                if text:
                    f_out.write(text_header(src.name, size, i, n, name, nxt).encode("utf-8"))
                while remaining > 0:
                    buf = f_in.read(min(remaining, 8 * 1024 * 1024))
                    if not buf:
                        break
                    digest.update(buf)
                    f_out.write(buf)
                    remaining -= len(buf)
                if text:
                    f_out.write(text_footer(i, n, nxt).encode("utf-8"))
            res.parts.append(p)
            say(f"  ✔ Parte {i}/{n}: {name} ({(b - a) / 1024 ** 2:.2f} MB)", "ok")
            if progress:
                progress(100 * b / max(1, size), f"Parte {i}/{n}")
    manifest = {"tool": f"{APP_NAME} v{APP_VERSION}", "source": src.name, "size": size,
                "sha256": digest.hexdigest(), "parts": [p.name for p in res.parts], "text_headers": text,
                "mode": mode, "created": datetime.datetime.now().isoformat(timespec="seconds")}
    res.manifest = out_dir / f"{stem}{ext}.split.json"
    res.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    say(f"SPLIT COMPLET: {len(res.parts)} parti → {out_dir}", "ok")
    return res


_HDR_START = (SEP_H + "\n").encode()
_FOOT_RE = re.compile(rb"\r?\n-{72}\r?\n END PART \d+ of \d+ .*?\r?\n-{72}\r?\n?\Z", re.S)


def strip_markers(data: bytes) -> bytes:
    """Remove a NexusX / UCeX v7 split header and footer from a text part (bytes in, bytes out)."""
    if data.startswith(_HDR_START) or data.startswith((SEP_H + "\r\n").encode()):
        first_nl = data.find(b"\n")
        end = data.find(SEP_H.encode(), first_nl + 1)
        if end != -1 and b"FISIER MAMA" in data[:end]:
            cut = end + len(SEP_H)
            if data[cut:cut + 2] == b"\r\n":
                cut += 2
            elif data[cut:cut + 1] == b"\n":
                cut += 1
            data = data[cut:]
    m = _FOOT_RE.search(data)
    if m:
        data = data[:m.start()]
        # v7 wrote footer as "\n" + sep..., NexusX identical; the leading newline belongs to the footer
    return data


def sort_parts(files: Sequence[str]) -> List[str]:
    def key(p):
        m = PART_RE.match(Path(p).name)
        return (0, m.group("stem"), int(m.group("n"))) if m else (1, Path(p).name.lower(), 0)
    return sorted(files, key=key)


def suggested_output_name(files: Sequence[str]) -> str:
    if not files:
        return "merged_output"
    m = PART_RE.match(Path(files[0]).name)
    return m.group("stem") if m else "merged_output"


def find_manifest(files: Sequence[str]) -> Optional[dict]:
    if not files:
        return None
    first = Path(files[0])
    m = PART_RE.match(first.name)
    if not m:
        return None
    mf = first.parent / f"{m.group('stem')}{m.group('ext') or ''}.split.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def merge_files(files: Sequence[str], out_path: Path, strip: Optional[bool] = None, progress: Progress = None,
                log: Log = None, stop: Optional[Callable[[], bool]] = None) -> MergeResult:
    say = log or (lambda m, t="info": None)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(files)
    res = MergeResult(output=out_path)
    manifest = find_manifest(files)
    # completeness check for partNNNofMMM sets
    nums, expected = [], None
    for f in files:
        m = PART_RE.match(Path(f).name)
        if m:
            nums.append(int(m.group("n")))
            expected = int(m.group("m"))
    if expected:
        res.missing = sorted(set(range(1, expected + 1)) - set(nums))
        if res.missing:
            say(f"⚠️ Lipsesc partile: {res.missing} din {expected}", "warn")
    if strip is None:
        strip = out_path.suffix.lower() in TEXT_EXTS
    say(f"START MERGE: {total} fisiere → {out_path.name} ({'TEXT, fara marcaje split' if strip else 'BINAR'})", "ok")
    digest = hashlib.sha256()
    with open(out_path, "wb") as f_out:
        for i, fp in enumerate(files, 1):
            if stop and stop():
                say("Merge oprit de utilizator.", "warn")
                break
            fp = Path(fp)
            say(f"  Adaug: {fp.name} ({fp.stat().st_size / 1024 ** 2:.2f} MB)", "info")
            if strip:
                data = strip_markers(fp.read_bytes())
                f_out.write(data)
                digest.update(data)
            else:
                with open(fp, "rb") as f_in:
                    for buf in iter(lambda: f_in.read(8 * 1024 * 1024), b""):
                        f_out.write(buf)
                        digest.update(buf)
            if progress:
                progress(100 * i / total, f"{i}/{total}")
    res.size = out_path.stat().st_size
    if manifest and manifest.get("sha256"):
        res.verified = digest.hexdigest() == manifest["sha256"]
        say("✅ Verificare SHA-256: identic cu fisierul original." if res.verified else
            "❌ Verificare SHA-256: rezultatul DIFERA de original (parti lipsa / modificate?)",
            "ok" if res.verified else "error")
    res.message = f"MERGE COMPLET: {out_path} ({res.size / 1024 ** 2:.2f} MB)"
    say(res.message, "ok")
    return res
