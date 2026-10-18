# -*- coding: utf-8 -*-
"""
OneNote extractor (UCeX v7.0 "OneNote Extractor" tab), GUI-independent.

v7 behaviour kept: .onepkg is a Microsoft Cabinet (MSCF); extraction is attempted with
ZIP → cabarchive → expand.exe → 7-Zip; per package an output folder with the extracted files,
a _text_export/ folder with "<section>_extracted.txt" (best-effort text from .one) and an
extraction report; optional "open folder after extraction".

Improvements:
  • built-in pure-Python CAB reader (stored + MSZIP) — works without 7-Zip/cabarchive/expand
  • text recovered from UTF-16LE as well as UTF-8 (OneNote stores page text mostly as UTF-16,
    which v7 could not see), noise filtered (GUIDs, binary garbage, duplicates)
  • images carved directly out of .one sections (PNG / JPEG / GIF) — "Extrage imagini" now
    really extracts the pictures pasted in notes; native image files are collected too
  • "Extrage atasamente" copies embedded files into _attachments/ (option existed but did nothing)
  • plain .one sections can be processed directly (no package needed)
  • combined Markdown export of the whole notebook, ready for search or AI
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .. import APP_NAME, APP_VERSION

Log = Optional[Callable[[str, str], None]]
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".emf", ".wmf", ".tif", ".tiff"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── CAB reader ───────────────────────────────────────────────────────────────
class CabError(Exception):
    pass


def read_cab(data: bytes) -> Dict[str, bytes]:
    """Return {name: content} for an MS Cabinet using no compression or MSZIP."""
    if data[:4] != b"MSCF":
        raise CabError("not a cabinet (missing MSCF signature)")
    (_sig, _r1, _cb, _r2, coff_files, _r3, _vmin, _vmaj, n_folders, n_files, flags, _set, _icab) = \
        struct.unpack_from("<4sIIIIIBBHHHHH", data, 0)
    pos = 36
    cb_hdr_res = cb_folder_res = cb_data_res = 0
    if flags & 0x0004:
        cb_hdr_res, cb_folder_res, cb_data_res = struct.unpack_from("<HBB", data, pos)
        pos += 4 + cb_hdr_res
    for flag in (0x0001, 0x0002):  # previous / next cabinet names
        if flags & flag:
            for _ in range(2):
                pos = data.index(b"\x00", pos) + 1
    folders: List[Tuple[int, int, int]] = []
    for _ in range(n_folders):
        coff, n_data, ctype = struct.unpack_from("<IHH", data, pos)
        folders.append((coff, n_data, ctype))
        pos += 8 + cb_folder_res
    folder_data: List[bytes] = []
    for coff, n_data, ctype in folders:
        kind = ctype & 0x000F
        if kind not in (0, 1):
            raise CabError({2: "Quantum", 3: "LZX"}.get(kind, str(kind)) + " compression not supported by built-in reader")
        out = bytearray()
        p = coff
        for _ in range(n_data):
            _csum, cb_data, _cb_unc = struct.unpack_from("<IHH", data, p)
            p += 8 + cb_data_res
            block = data[p:p + cb_data]
            p += cb_data
            if kind == 0:
                out += block
            else:
                if block[:2] != b"CK":
                    raise CabError("bad MSZIP block signature")
                history = bytes(out[-32768:])
                d = zlib.decompressobj(-15, zdict=history) if history else zlib.decompressobj(-15)
                out += d.decompress(block[2:]) + d.flush()
        folder_data.append(bytes(out))
    files: Dict[str, bytes] = {}
    pos = coff_files
    for _ in range(n_files):
        cb_file, off, ifolder, _date, _time, attribs = struct.unpack_from("<IIHHHH", data, pos)
        pos += 16
        end = data.index(b"\x00", pos)
        raw = data[pos:end]
        pos = end + 1
        name = raw.decode("utf-8" if attribs & 0x80 else "cp1252", errors="replace").replace("\\", "/")
        if ifolder >= len(folder_data):
            continue  # continued-from/to other cabinet
        files[name] = folder_data[ifolder][off:off + cb_file]
    return files


def _safe_join(root: Path, name: str) -> Path:
    target = (root / name).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise CabError(f"unsafe path in archive: {name}")
    return target


def _try_builtin(src: Path, dst: Path, log) -> bool:
    try:
        files = read_cab(src.read_bytes())
        for name, content in files.items():
            t = _safe_join(dst, name)
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(content)
        return bool(files)
    except CabError as e:
        log(f"   built-in CAB: {e}", "warn")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"   built-in CAB: {e}", "warn")
        return False


def _try_zip(src: Path, dst: Path, log) -> bool:
    try:
        if not zipfile.is_zipfile(str(src)):
            return False
        with zipfile.ZipFile(src) as z:
            for m in z.infolist():
                _safe_join(dst, m.filename)
            z.extractall(dst)
        return True
    except Exception:
        return False


def _try_cabarchive(src: Path, dst: Path, log) -> bool:
    try:
        import cabarchive  # type: ignore
    except ImportError:
        return False
    try:
        cab = cabarchive.CabArchive()
        cab.parse(src.read_bytes())
        for name, cf in cab.items():
            t = _safe_join(dst, name)
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(cf.buf)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"   cabarchive: {e}", "warn")
        return False


def _try_expand(src: Path, dst: Path, log) -> bool:
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(["expand", str(src), "-F:*", str(dst)], capture_output=True, timeout=300, creationflags=NO_WINDOW)
        return r.returncode == 0 and any(dst.iterdir())
    except Exception:
        return False


def _try_7zip(src: Path, dst: Path, log) -> bool:
    for exe in ("7z", "7za", r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        try:
            r = subprocess.run([exe, "x", str(src), f"-o{dst}", "-y"], capture_output=True, timeout=300, creationflags=NO_WINDOW)
            if r.returncode == 0:
                return True
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return False


EXTRACTORS = [("built-in CAB", _try_builtin), ("ZIP", _try_zip), ("cabarchive", _try_cabarchive),
              ("expand.exe", _try_expand), ("7-Zip", _try_7zip)]


# ── text & image recovery from .one ──────────────────────────────────────────
_GUID = re.compile(r"^\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?$")
_UTF16_RUN = re.compile(rb"(?:[\x09\x0a\x0d\x20-\x7e]\x00|[\xa0-\xff]\x00|[\x00-\xff][\x01-\x05\x1e\x20-\x27])"
                        rb"{6,}")
_UTF8_RUN = re.compile(rb"(?:[\x09\x0a\x0d\x20-\x7e]|[\xc2-\xf4][\x80-\xbf]{1,3}){6,}")
_NOISE = {"calibri", "arial", "segoe ui", "times new roman", "cambria", "consolas", "courier new", "normal",
          "microsoft onenote", "onenote", "en-us", "de-de", "ro-ro"}


def _good(s: str) -> bool:
    s = s.strip()
    if len(s) < 5 or _GUID.match(s) or s.lower() in _NOISE:
        return False
    letters = sum(ch.isalpha() for ch in s)
    spaces = s.count(" ")
    if letters < 3 or letters / len(s) < 0.45:
        return False
    if " " not in s and len(s) > 40 and not s.startswith(("http", "www", "\\\\")):
        return False  # long token without spaces = encoded data
    if any(ord(ch) < 9 or 0xE000 <= ord(ch) <= 0xF8FF or ch == "\ufffd" for ch in s):
        return False
    return spaces > 0 or letters >= 5


def extract_text(data: bytes, limit: int = 20000) -> str:
    """Best-effort readable text from a .one section (UTF-16LE + UTF-8), in file order, de-duplicated."""
    found: List[Tuple[int, str]] = []
    for align in (0, 1):
        for m in _UTF16_RUN.finditer(data, align):
            if (m.start() - align) % 2:
                continue
            try:
                s = m.group(0).decode("utf-16-le", errors="strict")
            except UnicodeDecodeError:
                continue
            for line in s.replace("\r", "\n").split("\n"):
                if _good(line):
                    found.append((m.start(), line.strip()))
    for m in _UTF8_RUN.finditer(data):
        try:
            s = m.group(0).decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line in s.replace("\r", "\n").split("\n"):
            if _good(line):
                found.append((m.start(), line.strip()))
    found.sort(key=lambda x: x[0])
    seen, out = set(), []
    for _pos, s in found:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return "\n".join(out)


def carve_images(data: bytes, min_size: int = 1024) -> List[Tuple[str, bytes]]:
    """Return [(ext, bytes)] for PNG/JPEG/GIF images embedded in a binary blob."""
    out: List[Tuple[str, bytes]] = []
    seen = set()
    for m in re.finditer(rb"\x89PNG\r\n\x1a\n", data):
        end = data.find(b"IEND", m.start())
        if end != -1:
            blob = data[m.start():end + 8]
            if len(blob) >= min_size and hash(blob) not in seen:
                seen.add(hash(blob))
                out.append((".png", blob))
    for m in re.finditer(rb"\xff\xd8\xff[\xdb\xe0\xe1\xe2\xe3\xe8\xee]", data):
        end = data.find(b"\xff\xd9", m.start() + 4)
        # skip nested thumbnail end markers: extend while another FFD9 follows closely after an EXIF block
        if end != -1:
            blob = data[m.start():end + 2]
            if len(blob) >= min_size and hash(blob) not in seen:
                seen.add(hash(blob))
                out.append((".jpg", blob))
    for m in re.finditer(rb"GIF8[79]a", data):
        end = data.find(b"\x00\x3b", m.start() + 6)
        if end != -1:
            blob = data[m.start():end + 2]
            if len(blob) >= min_size and hash(blob) not in seen:
                seen.add(hash(blob))
                out.append((".gif", blob))
    return out


# ── orchestration ────────────────────────────────────────────────────────────
@dataclass
class ExtractOptions:
    text: bool = True
    images: bool = True
    attachments: bool = True
    open_after: bool = False
    combined_markdown: bool = True


@dataclass
class PackageResult:
    source: Path
    out_dir: Path
    method: str = ""
    files: List[Path] = field(default_factory=list)
    sections: int = 0
    texts: List[Path] = field(default_factory=list)
    images: List[Path] = field(default_factory=list)
    attachments: List[Path] = field(default_factory=list)
    report: Optional[Path] = None
    markdown: Optional[Path] = None
    ok: bool = False


def _text_header(one_name: str, pkg_name: str) -> str:
    return (f"{'=' * 60}\n{APP_NAME} v{APP_VERSION} — OneNote Text Extractor\n"
            f"Fisier sursa : {one_name}\nPachet sursa : {pkg_name}\n"
            f"Data         : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"Nota: Continut extras best-effort din binar .one (UTF-16 + UTF-8).\n{'=' * 60}\n\n")


def process(src: Path, out_root: Path, opts: ExtractOptions, log: Log = None) -> PackageResult:
    say = log or (lambda m, t="info": None)
    src = Path(src)
    out_dir = Path(out_root) / src.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    res = PackageResult(source=src, out_dir=out_dir)
    if src.suffix.lower() == ".one":
        res.method = "sectiune .one directa"
        target = out_dir / src.name
        if target.resolve() != src.resolve():
            shutil.copy2(src, target)
        res.ok = True
    else:
        for label, fn in EXTRACTORS:
            say(f"   Incerc {label}…", "info")
            if fn(src, out_dir, say):
                say(f"   ✅ Extras cu {label}.", "ok")
                res.method, res.ok = label, True
                break
        if not res.ok:
            say("   ⚠ Extractie automata esuata (probabil compresie LZX).", "warn")
            say(f"   Sfat: instaleaza 7-Zip sau redenumeste '{src.name}' in '{src.stem}.cab' si deschide cu 7-Zip/WinRAR.", "warn")
            return res
    res.files = [f for f in out_dir.rglob("*") if f.is_file() and not f.name.startswith("_")
                 and "_text_export" not in f.parts and "_images" not in f.parts and "_attachments" not in f.parts]
    ones = [f for f in res.files if f.suffix.lower() == ".one"]
    res.sections = len(ones)
    native_imgs = [f for f in res.files if f.suffix.lower() in IMAGE_EXTS]
    say(f"   Fisiere extrase: {len(res.files)} | sectiuni .one: {len(ones)} | imagini: {len(native_imgs)}", "info")

    md_parts: List[str] = [f"# OneNote — {src.stem}\n\n*{APP_NAME} v{APP_VERSION} · {datetime.datetime.now():%Y-%m-%d %H:%M}*\n"]
    if opts.text and ones:
        txt_dir = out_dir / "_text_export"
        txt_dir.mkdir(exist_ok=True)
        for one in ones:
            text = extract_text(one.read_bytes())
            p = txt_dir / f"{one.stem}_extracted.txt"
            p.write_text(_text_header(one.name, src.name) + text, encoding="utf-8")
            res.texts.append(p)
            md_parts.append(f"\n## {one.stem}\n\n" + (text or "_(fara text detectabil)_") + "\n")
            say(f"   ✅ Text: {p.name} ({len(text.splitlines())} randuri)", "ok")
    if opts.images:
        img_dir = out_dir / "_images"
        for f in native_imgs:
            img_dir.mkdir(exist_ok=True)
            t = img_dir / f.name
            shutil.copy2(f, t)
            res.images.append(t)
        for one in ones:
            for k, (ext, blob) in enumerate(carve_images(one.read_bytes()), 1):
                img_dir.mkdir(exist_ok=True)
                t = img_dir / f"{one.stem}_img{k:03d}{ext}"
                t.write_bytes(blob)
                res.images.append(t)
        if res.images:
            say(f"   ✅ Imagini: {len(res.images)} → _images/", "ok")
    if opts.attachments:
        att = [f for f in res.files if f.suffix.lower() not in {".one", ".onetoc2", ".onepkg"} | IMAGE_EXTS]
        if att:
            adir = out_dir / "_attachments"
            adir.mkdir(exist_ok=True)
            for f in att:
                t = adir / f.name
                shutil.copy2(f, t)
                res.attachments.append(t)
            say(f"   ✅ Atasamente: {len(att)} → _attachments/", "ok")
    if opts.combined_markdown and res.texts:
        res.markdown = out_dir / f"{src.stem}_notebook.md"
        res.markdown.write_text("".join(md_parts), encoding="utf-8")
        say(f"   ✅ Markdown combinat: {res.markdown.name}", "ok")
    rpt = out_dir / "_UCeX_extraction_report.txt"
    with open(rpt, "w", encoding="utf-8") as rf:
        rf.write(f"{APP_NAME} v{APP_VERSION} — OneNote Extraction Report\n{'=' * 60}\n")
        rf.write(f"Sursa : {src}\nOutput: {out_dir}\nMetoda: {res.method}\nData  : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n{'=' * 60}\n\n")
        rf.write(f"Sectiuni .one: {res.sections} | Text: {len(res.texts)} | Imagini: {len(res.images)} | Atasamente: {len(res.attachments)}\n\n")
        for f in res.files:
            rf.write(f"  {f.relative_to(out_dir)}  ({f.stat().st_size:,} bytes)\n")
    res.report = rpt
    say(f"   📄 Raport: {rpt.name}", "ok")
    if opts.open_after:
        try:
            if os.name == "nt":
                os.startfile(str(out_dir))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(out_dir)])
        except Exception:
            pass
    return res
