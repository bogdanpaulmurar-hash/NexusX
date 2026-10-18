# -*- coding: utf-8 -*-
"""
Link extraction (ULaE v2.0 extractor.py), substantially extended.

DOCX — parsed directly from the OOXML package (no python-docx needed), so it now finds
links that v2.0 missed:
  • headers, footers, footnotes, endnotes, comments, text boxes, content controls (TOC!)
  • HYPERLINK *fields* (Word often stores links as field codes, not <w:hyperlink>)
  • cross-references REF / PAGEREF / NOTEREF  → validated against bookmarks
    ("links from one section to another")
  • TOC entries (_Toc bookmarks), linked pictures (a:hlinkClick), INCLUDETEXT/INCLUDEPICTURE/LINK
  • nested tables, merged cells counted once
  • every link carries the Word heading (§ section) it sits in and, for internal links,
    the heading/text of the target
PDF  — PyMuPDF (as before) → pypdf → raw /URI scan fallback.
XLSX / PPTX — hyperlinks, HYPERLINK() formulas, slide jumps, text URLs.
HTML — href/src/action with line numbers, <base>, relative files, #id anchors checked.
Markdown — [text](url), <url>, heading anchors (#slug) checked, relative files.
TXT/LOG/CSV/JSON/XML/URL — line based.
mailto:, file:// and UNC (\\\\server\\share) targets are now captured too.
"""
from __future__ import annotations

import configparser
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlparse
from xml.etree import ElementTree as ET

from .models import LinkRecord

URL_REGEX = re.compile(
    r"""(?ix)
    (?:\b(?:https?://|ftp://|file:///?|www\.)[^\s<>"'`]+)
    | (?:\bmailto:[^\s<>"'`]+)
    | (?:\\\\[A-Za-z0-9_.\-$]+\\[^\s<>"'|*?]+)
    """)

SUPPORTED_EXTENSIONS = {
    ".docx", ".docm", ".dotx", ".dotm", ".pdf", ".txt", ".html", ".htm", ".md", ".markdown",
    ".log", ".csv", ".xlsx", ".xlsm", ".pptx", ".pptm", ".url", ".xml", ".json",
}

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
}
W = "{%s}" % NS["w"]
R = "{%s}" % NS["r"]
A = "{%s}" % NS["a"]

_HEADING_STYLE = re.compile(r"(?i)^(heading|berschrift|überschrift|titre|titel|title|kop|rubrik|nagłówek|titlu)\s*\d*")


# ── URL helpers ──────────────────────────────────────────────────────────────
def clean_url(u: str) -> str:
    if not u:
        return ""
    u = u.strip().strip("<>")
    u = u.rstrip(".,;:!?]}>\"'")
    # keep balanced parentheses (e.g. Wikipedia URLs)
    while u.endswith(")") and u.count("(") < u.count(")"):
        u = u[:-1]
    return u.strip()


def is_valid_url(u: str) -> bool:
    if not u or len(u) < 4:
        return False
    low = u.lower()
    if low.startswith("#bookmark="):
        return True
    if low.startswith(("http://", "https://", "ftp://", "www.")):
        if low.endswith(("=", "...", "..")) or low in ("http://", "https://", "www."):
            return False
        return True
    if low.startswith("mailto:"):
        return "@" in u
    if low.startswith("file:"):
        return len(u) > 8
    if u.startswith("\\\\"):
        return len(u.split("\\")) >= 4
    return False


def _norm_text(s: str) -> str:
    return " ".join((s or "").split())


class _Collector:
    """Accumulates LinkRecords for one file (ULaE add_entry semantics)."""

    def __init__(self, path: Path):
        self.path = path
        self.items: List[LinkRecord] = []

    def add(self, url_raw: str, loc: str, anchor: str = "", ctx: str = "", src: str = "Text URL",
            status: str = "Not checked", evidence: str = "", error: str = "",
            section: str = "", target_section: str = "") -> None:
        cleaned = clean_url(url_raw) if not url_raw.startswith("#bookmark=") else url_raw.strip()
        if not is_valid_url(cleaned):
            return
        self.items.append(LinkRecord(
            file=self.path.name, path=str(self.path), location=loc, url=cleaned,
            anchor=_norm_text(anchor)[:300], context=_norm_text(ctx)[:600], source=src,
            status=status, http_code="Internal" if cleaned.startswith("#") else "",
            evidence=evidence, error=error, section=_norm_text(section)[:200],
            target_section=_norm_text(target_section)[:200]))

    def text_urls(self, text: str, loc: str, section: str = "", src: str = "Text URL") -> None:
        for m in URL_REGEX.finditer(text or ""):
            self.add(m.group(0), loc, m.group(0), text, src, section=section)

    def bookmark(self, name: str, loc: str, label: str, ctx: str, src: str, section: str,
                 bookmarks: Dict[str, Tuple[str, str, str]], kind: str = "Bookmark") -> None:
        info = bookmarks.get(name)
        if info:
            tloc, ttext, tsec = info
            tgt = ttext or tsec or "Section"
            self.add(f"#bookmark={name}", loc, label or name, ctx, src, status="Bookmark OK",
                     evidence=f'Valid {kind} -> Targets {tloc}: "{tgt[:90]}"', section=section,
                     target_section=tsec or ttext)
        else:
            self.add(f"#bookmark={name}", loc, label or name, ctx, src, status="Broken Bookmark",
                     evidence=f"Broken internal link -> Target bookmark '{name}' does not exist in this document",
                     error=f"Bookmark target '{name}' missing from document (broken cross-reference)",
                     section=section)


# ── DOCX ─────────────────────────────────────────────────────────────────────
def _read_rels(zf: zipfile.ZipFile, part: str) -> Dict[str, Tuple[str, str]]:
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", name + ".rels")
    out: Dict[str, Tuple[str, str]] = {}
    try:
        root = ET.fromstring(zf.read(rels_path))
    except Exception:
        return out
    for rel in root:
        out[rel.get("Id", "")] = (rel.get("Target", ""), rel.get("TargetMode", ""))
    return out


_FIELD_RE = re.compile(r'^\s*(\w+)\s*(.*)$', re.S)


def _parse_field(instr: str) -> Tuple[str, List[str], Dict[str, str]]:
    """Parse a Word field instruction → (NAME, positional args, switches)."""
    m = _FIELD_RE.match(instr or "")
    if not m:
        return "", [], {}
    name = m.group(1).upper()
    rest = m.group(2)
    tokens = re.findall(r'"([^"]*)"|(\\[\*@#!a-zA-Z])|(\S+)', rest)
    args: List[str] = []
    switches: Dict[str, str] = {}
    pending: Optional[str] = None
    for quoted, switch, bare in tokens:
        if switch:
            pending = switch.lower()
            switches[pending] = ""
            continue
        val = quoted if quoted or (not bare) else bare
        if pending is not None:
            switches[pending] = val
            pending = None
        else:
            args.append(val)
    return name, args, switches


class _DocxWalker:
    def __init__(self, zf: zipfile.ZipFile, col: _Collector):
        self.zf = zf
        self.col = col
        self.bookmarks: Dict[str, Tuple[str, str, str]] = {}
        self.section = ""

    # paragraph helpers
    @staticmethod
    def p_text(p: ET.Element) -> str:
        parts = []
        for node in p.iter():
            if node.tag == W + "t" and node.text:
                parts.append(node.text)
            elif node.tag == W + "tab":
                parts.append(" ")
        return "".join(parts)

    @staticmethod
    def is_heading(p: ET.Element) -> bool:
        ppr = p.find(W + "pPr")
        if ppr is None:
            return False
        st = ppr.find(W + "pStyle")
        if st is not None and _HEADING_STYLE.match(st.get(W + "val", "") or ""):
            return True
        return ppr.find(W + "outlineLvl") is not None

    def iter_blocks(self, container: ET.Element, loc_prefix: str):
        """Yield (paragraph_element, location_label) in document order, descending into tables/sdt."""
        p_idx = 0
        t_idx = 0
        for child in list(container):
            tag = child.tag
            if tag == W + "p":
                p_idx += 1
                yield child, f"{loc_prefix}Paragraph {p_idx}" if not loc_prefix else f"{loc_prefix} ¶{p_idx}"
            elif tag == W + "tbl":
                t_idx += 1
                tlabel = f"{loc_prefix}Table {t_idx}" if not loc_prefix else f"{loc_prefix} > Table {t_idx}"
                for r_i, tr in enumerate(child.findall(W + "tr"), 1):
                    for c_i, tc in enumerate(tr.findall(W + "tc"), 1):
                        cell_loc = f"{tlabel}, Row {r_i}, Col {c_i}"
                        for p, inner in self.iter_blocks(tc, cell_loc):
                            yield p, (inner if inner.startswith(cell_loc + " > ") else cell_loc)
            elif tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    for p, loc in self.iter_blocks(content, loc_prefix):
                        yield p, loc
            elif tag in (W + "customXml", W + "smartTag"):
                for p, loc in self.iter_blocks(child, loc_prefix):
                    yield p, loc

    def collect_bookmarks(self, root: ET.Element, part_label: str) -> None:
        pending: List[str] = []
        section = ""
        for p, loc in self.iter_blocks(root, part_label):
            txt = self.p_text(p).strip()
            if self.is_heading(p) and txt:
                section = txt
            names = [b.get(W + "name") for b in p.iter(W + "bookmarkStart")]
            names = [n for n in names if n and n != "_GoBack"]
            for n in pending + names:
                self.bookmarks[n] = (loc, txt[:90], section)
            pending = [] if txt else (pending + names)
        # bookmarks placed between body paragraphs (siblings) — attach to nearest
        for b in root.iter(W + "bookmarkStart"):
            n = b.get(W + "name")
            if n and n != "_GoBack" and n not in self.bookmarks:
                self.bookmarks[n] = (part_label or "Body", "", section)

    def walk_part(self, part: str, root: ET.Element, part_label: str) -> None:
        rels = _read_rels(self.zf, part)
        self.section = ""
        for p, loc in self.iter_blocks(root, part_label):
            text = self.p_text(p)
            if self.is_heading(p) and text.strip():
                self.section = text.strip()
            self.paragraph(p, loc, text, rels)

    def _rel_target(self, rels, rid: str) -> str:
        target, _mode = rels.get(rid, ("", ""))
        return target

    def paragraph(self, p: ET.Element, loc: str, text: str, rels) -> None:
        col, sec = self.col, self.section
        # 1. visible text URLs
        col.text_urls(text, loc, sec)
        # 2. <w:hyperlink>
        for h in p.iter(W + "hyperlink"):
            rid = h.get(R + "id")
            anchor = h.get(W + "anchor")
            label = "".join(t.text or "" for t in h.iter(W + "t"))
            target = self._rel_target(rels, rid) if rid else ""
            if target:
                full = target + (f"#{anchor}" if anchor and "#" not in target else "")
                col.add(full, loc, label, text, "DOCX hyperlink", section=sec)
            elif anchor:
                src = "DOCX TOC entry" if anchor.startswith("_Toc") else "DOCX internal bookmark"
                col.bookmark(anchor, loc, label, text, src, sec, self.bookmarks)
        # 3. pictures / shapes with links
        for hl in p.iter(A + "hlinkClick"):
            rid = hl.get(R + "id")
            target = self._rel_target(rels, rid) if rid else ""
            if target:
                col.add(target, loc, "[linked image/shape]", text, "DOCX image hyperlink", section=sec)
        # 4. fields (simple + complex)
        for fs in p.iter(W + "fldSimple"):
            label = "".join(t.text or "" for t in fs.iter(W + "t"))
            self.field(fs.get(W + "instr", ""), label, loc, text)
        self.complex_fields(p, loc, text)

    def complex_fields(self, p: ET.Element, loc: str, text: str) -> None:
        stack: List[Dict[str, object]] = []
        for node in p.iter():
            tag = node.tag
            if tag == W + "fldChar":
                t = node.get(W + "fldCharType")
                if t == "begin":
                    stack.append({"instr": [], "result": [], "phase": "instr"})
                elif t == "separate" and stack:
                    stack[-1]["phase"] = "result"
                elif t == "end" and stack:
                    f = stack.pop()
                    self.field("".join(f["instr"]), "".join(f["result"]), loc, text)  # type: ignore[arg-type]
            elif tag == W + "instrText" and stack and stack[-1]["phase"] == "instr":
                stack[-1]["instr"].append(node.text or "")  # type: ignore[union-attr]
            elif tag == W + "t" and stack and stack[-1]["phase"] == "result":
                stack[-1]["result"].append(node.text or "")  # type: ignore[union-attr]

    def field(self, instr: str, label: str, loc: str, ctx: str) -> None:
        name, args, sw = _parse_field(instr)
        col, sec = self.col, self.section
        if name == "HYPERLINK":
            target = args[0] if args else ""
            anchor = sw.get("\\l", "")
            if target:
                col.add(target + (f"#{anchor}" if anchor else ""), loc, label, ctx, "DOCX HYPERLINK field", section=sec)
            elif anchor:
                col.bookmark(anchor, loc, label, ctx, "DOCX HYPERLINK field (internal)", sec, self.bookmarks)
        elif name in ("REF", "PAGEREF", "NOTEREF") and args:
            bm = args[0]
            if bm:  # REF/PAGEREF/NOTEREF always point at a bookmark
                col.bookmark(bm, loc, label or bm, ctx, f"DOCX cross-reference ({name})", sec, self.bookmarks,
                             kind="Cross-reference")
        elif name in ("INCLUDETEXT", "INCLUDEPICTURE", "LINK", "DDEAUTO", "DDE") and args:
            target = args[-1] if name in ("LINK", "DDE", "DDEAUTO") and len(args) > 1 else args[0]
            if name in ("LINK", "DDE", "DDEAUTO") and len(args) >= 2:
                target = args[1]
            t = target.replace("\\\\", "\\")
            if re.match(r"^[A-Za-z]:\\", t):
                t = "file:///" + t.replace("\\", "/")
            col.add(t, loc, label or name, ctx, f"DOCX {name} field", section=sec)


def _extract_docx(path: Path, col: _Collector) -> None:
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        parts: List[Tuple[str, str]] = [("word/document.xml", "")]
        for n in sorted(names):
            base = posixpath.basename(n)
            if n.startswith("word/") and n.count("/") == 1:
                if re.match(r"header\d*\.xml$", base):
                    parts.append((n, f"Header ({base})"))
                elif re.match(r"footer\d*\.xml$", base):
                    parts.append((n, f"Footer ({base})"))
                elif base in ("footnotes.xml", "endnotes.xml", "comments.xml"):
                    parts.append((n, base.replace(".xml", "").capitalize()))
        walker = _DocxWalker(zf, col)
        roots: List[Tuple[str, ET.Element, str]] = []
        for part, label in parts:
            if part not in names:
                continue
            try:
                xml = ET.fromstring(zf.read(part))
            except ET.ParseError:
                continue
            container = xml.find(W + "body") if part == "word/document.xml" else xml
            if container is None:
                continue
            if part != "word/document.xml":
                # footnotes/comments: each child is a note/comment container
                if label in ("Footnotes", "Endnotes", "Comments"):
                    for i, note in enumerate(list(container), 1):
                        roots.append((part, note, f"{label[:-1]} {i}"))
                    continue
            roots.append((part, container, label))
        for part, cont, label in roots:
            walker.collect_bookmarks(cont, label)
        for part, cont, label in roots:
            walker.walk_part(part, cont, label)


# ── XLSX ─────────────────────────────────────────────────────────────────────
def _extract_xlsx(path: Path, col: _Collector) -> None:
    S = "{%s}" % NS["s"]
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        wb_rels = _read_rels(zf, "xl/workbook.xml")
        sheets: List[Tuple[str, str]] = []
        for sh in wb.iter(S + "sheet"):
            rid = sh.get(R + "id")
            target = wb_rels.get(rid, ("", ""))[0]
            part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
            sheets.append((sh.get("name", "Sheet"), part))
        sheet_names = {n.lower() for n, _ in sheets}
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            ss = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss.iter(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")))
        for sname, part in sheets:
            if part not in names:
                continue
            xml = ET.fromstring(zf.read(part))
            rels = _read_rels(zf, part)
            for hl in xml.iter(S + "hyperlink"):
                ref = hl.get("ref", "")
                loc = f"Sheet '{sname}'!{ref}"
                rid = hl.get(R + "id")
                display = hl.get("display", "")
                if rid and rels.get(rid):
                    target = rels[rid][0]
                    if hl.get("location"):
                        target += "#" + hl.get("location")
                    col.add(target, loc, display, "", "XLSX hyperlink")
                elif hl.get("location"):
                    tgt = hl.get("location", "")
                    sheet_part = tgt.split("!")[0].strip("'").lower()
                    ok = sheet_part in sheet_names
                    col.add(f"#bookmark={tgt}", loc, display or tgt, "", "XLSX internal link",
                            status="Bookmark OK" if ok else "Broken Bookmark",
                            evidence=f"Targets sheet location {tgt}" if ok else f"Sheet '{sheet_part}' not found",
                            error="" if ok else f"Internal link target '{tgt}' missing")
            for c in xml.iter(S + "c"):
                ref = c.get("r", "")
                f = c.find(S + "f")
                if f is not None and f.text and "HYPERLINK" in f.text.upper():
                    m = re.search(r'HYPERLINK\(\s*"([^"]+)"', f.text, re.I)
                    if m:
                        col.add(m.group(1), f"Sheet '{sname}'!{ref}", "", f.text, "XLSX HYPERLINK() formula")
                v = c.find(S + "v")
                if v is not None and v.text:
                    val = v.text
                    if c.get("t") == "s":
                        try:
                            val = shared[int(val)]
                        except (ValueError, IndexError):
                            continue
                    col.text_urls(val, f"Sheet '{sname}'!{ref}")
                is_ = c.find(S + "is")
                if is_ is not None:
                    col.text_urls("".join(t.text or "" for t in is_.iter(S + "t")), f"Sheet '{sname}'!{ref}")


# ── PPTX ─────────────────────────────────────────────────────────────────────
def _extract_pptx(path: Path, col: _Collector) -> None:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                        key=lambda n: int(re.findall(r"\d+", n)[-1]))
        existing = set(names)
        for n in slides:
            num = int(re.findall(r"\d+", n)[-1])
            loc = f"Slide {num}"
            xml = ET.fromstring(zf.read(n))
            rels = _read_rels(zf, n)
            text = " ".join(t.text or "" for t in xml.iter(A + "t"))
            col.text_urls(text, loc)
            for tag in ("hlinkClick", "hlinkMouseOver"):
                for hl in xml.iter(A + tag):
                    rid = hl.get(R + "id")
                    action = hl.get("action", "") or ""
                    target, mode = rels.get(rid, ("", "")) if rid else ("", "")
                    if "hlinksldjump" in action and target:
                        tpart = posixpath.normpath(posixpath.join("ppt/slides", target))
                        ok = tpart in existing
                        col.add(f"#bookmark={posixpath.basename(target)}", loc, "slide jump", text,
                                "PPTX slide link", status="Bookmark OK" if ok else "Broken Bookmark",
                                evidence=f"Jumps to {posixpath.basename(target)}" if ok else "Target slide missing",
                                error="" if ok else f"Slide {target} not found")
                    elif target and mode == "External":
                        col.add(target, loc, "", text, "PPTX hyperlink")


# ── PDF ──────────────────────────────────────────────────────────────────────
def _extract_pdf(path: Path, col: _Collector) -> None:
    fitz = None
    try:
        import pymupdf as fitz  # type: ignore
    except Exception:
        try:
            import fitz  # type: ignore
        except Exception:
            fitz = None
    if fitz is not None:
        with fitz.open(str(path)) as doc:
            toc_names = set()
            for page_num, page in enumerate(doc, 1):
                txt = page.get_text() or ""
                for link in page.get_links():
                    uri = link.get("uri")
                    if uri:
                        col.add(uri, f"Page {page_num}", "", txt[:600], "PDF annotation")
                    elif link.get("kind") == 1 or link.get("page") is not None:  # internal GoTo
                        tp = link.get("page", -1)
                        ok = 0 <= tp < len(doc)
                        name = f"page{tp + 1}"
                        if name in toc_names:
                            continue
                        toc_names.add(name)
                        col.add(f"#bookmark={name}", f"Page {page_num}", "", txt[:300], "PDF internal link",
                                status="Bookmark OK" if ok else "Broken Bookmark",
                                evidence=f"Jumps to page {tp + 1}" if ok else "Target page missing",
                                error="" if ok else f"Target page {tp + 1} does not exist")
                col.text_urls(txt, f"Page {page_num}")
        return
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, 1):
            txt = page.extract_text() or ""
            col.text_urls(txt, f"Page {i}")
            for annot in page.get("/Annots") or []:
                try:
                    a = annot.get_object().get("/A")
                    if a and a.get("/URI"):
                        col.add(str(a["/URI"]), f"Page {i}", "", txt[:600], "PDF annotation")
                except Exception:
                    continue
        return
    except Exception:
        pass
    raw = path.read_bytes()
    for m in re.finditer(rb"/URI\s*\(((?:\\.|[^\\)])*)\)", raw):
        col.add(m.group(1).decode("latin-1", "replace").replace("\\", ""), "PDF (raw scan)", "", "", "PDF annotation")


# ── HTML ─────────────────────────────────────────────────────────────────────
class _HtmlLinks(HTMLParser):
    ATTRS = {"a": "href", "area": "href", "link": "href", "img": "src", "script": "src",
             "iframe": "src", "form": "action", "source": "src", "embed": "src"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Tuple[str, str, int, str]] = []  # (tag, url, line, text)
        self.ids: set = set()
        self.base: str = ""
        self._open_a: Optional[List] = None
        self.headings: List[Tuple[int, str]] = []
        self._in_h: Optional[List] = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for key in ("id", "name"):
            if d.get(key):
                self.ids.add(d[key])
        if tag == "base" and d.get("href"):
            self.base = d["href"]
        if tag in ("h1", "h2", "h3", "h4"):
            self._in_h = [self.getpos()[0], ""]
        attr = self.ATTRS.get(tag)
        if attr and d.get(attr):
            entry = [tag, d[attr], self.getpos()[0], d.get("title", "") or d.get("alt", "")]
            self.links.append(entry)  # type: ignore[arg-type]
            if tag == "a":
                self._open_a = entry

    def handle_data(self, data):
        if self._open_a is not None:
            self._open_a[3] = (self._open_a[3] + " " + data).strip()
        if self._in_h is not None:
            self._in_h[1] += data

    def handle_endtag(self, tag):
        if tag == "a":
            self._open_a = None
        if tag in ("h1", "h2", "h3", "h4") and self._in_h is not None:
            self.headings.append((self._in_h[0], self._in_h[1].strip()))
            self._in_h = None


def _section_for_line(headings: List[Tuple[int, str]], line: int) -> str:
    sec = ""
    for ln, txt in headings:
        if ln <= line:
            sec = txt
        else:
            break
    return sec


def _local_target(base_dir: Path, rel: str) -> Optional[Path]:
    rel = unquote(rel.split("#")[0].split("?")[0])
    if not rel:
        return None
    p = (base_dir / rel)
    return p


def _extract_html(path: Path, col: _Collector, text: str) -> None:
    parser = _HtmlLinks()
    try:
        parser.feed(text)
    except Exception:
        pass
    lines = text.splitlines()
    for tag, url, line, label in parser.links:
        url = url.strip()
        ctx = lines[line - 1].strip() if 0 < line <= len(lines) else ""
        sec = _section_for_line(parser.headings, line)
        loc = f"Line {line}"
        low = url.lower()
        if low.startswith(("javascript:", "data:", "tel:", "about:")):
            continue
        if url.startswith("#"):
            name = url[1:]
            if not name:
                continue
            ok = name in parser.ids
            col.add(f"#bookmark={name}", loc, label, ctx, "HTML in-page anchor",
                    status="Bookmark OK" if ok else "Broken Bookmark",
                    evidence=f"Element id/name '{name}' exists" if ok else f"No element with id/name '{name}'",
                    error="" if ok else f"Anchor '#{name}' not found in page", section=sec)
            continue
        if parser.base and not urlparse(url).scheme:
            url = urljoin(parser.base, url)
        if urlparse(url).scheme in ("http", "https", "ftp", "mailto", "file") or url.startswith("\\\\") or low.startswith("www."):
            col.add(url, loc, label, ctx, f"HTML <{tag}>", section=sec)
        else:
            target = _local_target(path.parent, url)
            if target is not None:
                col.add(target.resolve().as_uri(), loc, label or url, ctx, f"HTML <{tag}> (relative)", section=sec)
    for i, line in enumerate(lines, 1):
        if "http" in line or "www." in line:
            # visible text URLs outside attributes
            stripped = re.sub(r"<[^>]+>", " ", line)
            col.text_urls(stripped, f"Line {i}", _section_for_line(parser.headings, i))


# ── Markdown ─────────────────────────────────────────────────────────────────
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\(\s*<?((?:[^()\s>]|\([^()\s]*\))+)>?(?:\s+\"[^\"]*\")?\s*\)")
_MD_REF = re.compile(r"^\s*\[([^\]]+)\]:\s*<?(\S+?)>?(?:\s+\".*\")?\s*$")
_MD_AUTOLINK = re.compile(r"<((?:https?|ftp|mailto):[^>\s]+)>")


def _md_slug(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")


def _extract_md(path: Path, col: _Collector, text: str) -> None:
    lines = text.splitlines()
    slugs = set()
    headings: List[Tuple[int, str]] = []
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
        m = re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m and not in_code:
            headings.append((i, m.group(1)))
            slug = _md_slug(m.group(1))
            base, k = slug, 1
            while slug in slugs:
                slug = f"{base}-{k}"
                k += 1
            slugs.add(slug)
        for a in re.findall(r'<a\s+(?:name|id)="([^"]+)"', line):
            slugs.add(a)
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith(("```", "~~~")):
            in_code = not in_code
            continue
        sec = _section_for_line(headings, i)
        loc = f"Line {i}"
        spans = []
        for m in list(_MD_LINK.finditer(line)) + list(_MD_REF.finditer(line)):
            label, url = m.group(1), m.group(2)
            spans.append(m.span())
            if url.startswith("#"):
                name = url[1:]
                ok = name.lower() in {s.lower() for s in slugs}
                col.add(f"#bookmark={name}", loc, label, line, "Markdown heading anchor",
                        status="Bookmark OK" if ok else "Broken Bookmark",
                        evidence=f"Heading anchor '#{name}' exists" if ok else f"No heading for '#{name}'",
                        error="" if ok else f"Anchor '#{name}' not found", section=sec)
            elif urlparse(url).scheme or url.lower().startswith("www."):
                col.add(url, loc, label, line, "Markdown link", section=sec)
            else:
                target = _local_target(path.parent, url)
                if target is not None:
                    col.add(target.resolve().as_uri(), loc, label or url, line, "Markdown link (relative)", section=sec)
        for m in _MD_AUTOLINK.finditer(line):
            spans.append(m.span())
            col.add(m.group(1), loc, m.group(1), line, "Markdown autolink", section=sec)
        if not in_code:
            rest = line
            for a, b in sorted(spans, reverse=True):
                rest = rest[:a] + " " * (b - a) + rest[b:]
            col.text_urls(rest, loc, sec)


# ── public API ───────────────────────────────────────────────────────────────
def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_from_file(path: Path) -> List[LinkRecord]:
    """
    Extract every link from a document. Deduplicates by URL per file and merges
    locations (ULaE v2.0 behaviour), counting occurrences.
    """
    path = Path(path)
    col = _Collector(path)
    ext = path.suffix.lower()
    try:
        if ext in (".docx", ".docm", ".dotx", ".dotm"):
            _extract_docx(path, col)
        elif ext in (".xlsx", ".xlsm"):
            _extract_xlsx(path, col)
        elif ext in (".pptx", ".pptm"):
            _extract_pptx(path, col)
        elif ext == ".pdf":
            _extract_pdf(path, col)
        elif ext == ".url":
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(_read_text_file(path))
            for sec in cp.sections():
                if cp.has_option(sec, "URL"):
                    col.add(cp.get(sec, "URL"), "Internet shortcut", path.stem, "", "Windows .url shortcut")
        else:
            text = _read_text_file(path)
            if ext in (".html", ".htm"):
                _extract_html(path, col, text)
            elif ext in (".md", ".markdown"):
                _extract_md(path, col, text)
            else:
                for line_num, line in enumerate(text.splitlines(), 1):
                    col.text_urls(line, f"Line {line_num}")
    except zipfile.BadZipFile:
        col.items.append(LinkRecord(file=path.name, path=str(path), location="File error", url="#bookmark=__file_error__",
                                    status="Broken", error="File is not a valid Office package (corrupt or password protected)",
                                    source="Error"))
    except Exception as e:  # noqa: BLE001
        col.items.append(LinkRecord(file=path.name, path=str(path), location="File error", url="#bookmark=__file_error__",
                                    status="Broken", error=f"Error parsing {ext}: {e}", source="Error"))
    return merge_duplicates(col.items)


def merge_duplicates(items: List[LinkRecord]) -> List[LinkRecord]:
    grouped: Dict[str, LinkRecord] = {}
    for item in items:
        g = grouped.get(item.url)
        if g is None:
            grouped[item.url] = item
            continue
        g.occurrences += 1
        if item.location not in g.location.split(" | "):
            g.location += f" | {item.location}"
        if not g.anchor and item.anchor:
            g.anchor = item.anchor
        if not g.section and item.section:
            g.section = item.section
        if item.status != "Not checked" and g.status == "Not checked":
            g.status, g.evidence, g.error, g.http_code = item.status, item.evidence, item.error, item.http_code
        if item.source not in g.source.split(" + "):
            g.source += f" + {item.source}"
    return list(grouped.values())


def collect_files(folder: Path) -> List[Path]:
    return sorted(p for p in Path(folder).rglob("*")
                  if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS and not p.name.startswith("~$"))
