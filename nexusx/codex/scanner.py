# -*- coding: utf-8 -*-
"""
Folder scanner (UCeX v6.7 _scan_thread / _populate_tree), improved:
  • os.scandir based walk (faster on OneDrive/network folders)
  • stop flag + progress callback
  • binary detection, optional .gitignore support
  • MD5 + line counting in a thread pool (v6.7 did it serially on the GUI thread)
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set

from .constants import DEFAULT_EXCLUDED

MB = 1024 * 1024


@dataclass
class ScanOptions:
    recursive: bool = True
    skip_hidden: bool = True
    max_bytes: int = 5 * MB
    excluded: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDED.split(",")))
    respect_gitignore: bool = False

    @classmethod
    def full(cls, respect_gitignore: bool = False) -> "ScanOptions":
        """'Full Scan' defaults from UCeX: recursive, skip hidden, 5 MB, default exclusions."""
        return cls(respect_gitignore=respect_gitignore)


@dataclass
class FileInfo:
    path: Path
    rel: str
    ext: str
    size: int
    lines: Optional[int] = None
    md5: Optional[str] = None
    binary: bool = False


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except Exception:
        return "N/A"
    return h.hexdigest()


def count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as f:
            n = 0
            last = b""
            for chunk in iter(lambda: f.read(1 << 16), b""):
                n += chunk.count(b"\n")
                last = chunk
            if last and not last.endswith(b"\n"):
                n += 1
            return n
    except Exception:
        return 0


_TEXT_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")


def is_binary(path: Path, sniff: int = 8192) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(sniff)
    except Exception:
        return True
    if not head:
        return False
    if head.startswith(_TEXT_BOMS):
        return False
    if b"\x00" in head:
        return True
    # high ratio of control chars → binary
    ctrl = sum(1 for b in head if b < 9 or (13 < b < 32))
    return ctrl / len(head) > 0.30


def read_text(path: Path) -> str:
    """Read text robustly: utf-8 (with BOM), utf-16 (BOM), cp1252 fallback."""
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


class _GitIgnore:
    def __init__(self, root: Path):
        self.patterns: List[str] = []
        gi = root / ".gitignore"
        if gi.exists():
            try:
                for line in read_text(gi).splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("!"):
                        self.patterns.append(line)
            except Exception:
                pass

    def ignored(self, rel: str, is_dir: bool) -> bool:
        rel = rel.replace("\\", "/")
        name = rel.rsplit("/", 1)[-1]
        for p in self.patterns:
            dir_only = p.endswith("/")
            pat = p.rstrip("/").lstrip("/")
            if dir_only and not is_dir:
                continue
            if "/" in pat:
                if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + "/*"):
                    return True
            elif fnmatch.fnmatch(name, pat):
                return True
        return False


def scan_folder(root: Path, opts: ScanOptions,
                progress: Optional[Callable[[int], None]] = None,
                stop: Optional[Callable[[], bool]] = None) -> List[Path]:
    """Return all files under root honouring the options (no extension filter — same as UCeX)."""
    root = Path(root)
    out: List[Path] = []
    gi = _GitIgnore(root) if opts.respect_gitignore else None
    excl = {e.strip() for e in opts.excluded if e.strip()}
    stack = [root]
    while stack:
        if stop and stop():
            break
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name.lower())
        except (PermissionError, FileNotFoundError, OSError):
            continue
        for entry in entries:
            name = entry.name
            if opts.skip_hidden and name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            rel = os.path.relpath(entry.path, root)
            if is_dir:
                if not opts.recursive or name in excl:
                    continue
                if gi and gi.ignored(rel, True):
                    continue
                stack.append(Path(entry.path))
                continue
            if gi and gi.ignored(rel, False):
                continue
            try:
                if entry.stat().st_size <= opts.max_bytes:
                    out.append(Path(entry.path))
            except OSError:
                pass
        if progress:
            progress(len(out))
    out.sort(key=lambda p: str(p).lower())
    return out


def enrich(files: Iterable[Path], root: Path, with_md5: bool = True, with_lines: bool = True,
           workers: int = 4, stop: Optional[Callable[[], bool]] = None) -> List[FileInfo]:
    """Compute size/lines/md5/binary flag in parallel."""
    root = Path(root)

    def one(fp: Path) -> FileInfo:
        try:
            rel = str(fp.relative_to(root))
        except ValueError:
            rel = str(fp)
        try:
            size = fp.stat().st_size
        except OSError:
            size = 0
        info = FileInfo(path=fp, rel=rel, ext=fp.suffix.lower() or fp.name.lower(), size=size)
        if stop and stop():
            return info
        info.binary = is_binary(fp)
        if with_lines and not info.binary:
            info.lines = count_lines(fp)
        if with_md5:
            info.md5 = md5_file(fp)
        return info

    files = list(files)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, files))
