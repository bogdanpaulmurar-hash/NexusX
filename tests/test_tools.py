# -*- coding: utf-8 -*-
"""Tests for Split & Merge and the OneNote extractor (UCeX v7 features)."""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexusx.tools import onenote, splitmerge  # noqa: E402


def make_cab(files: dict, mszip: bool = True) -> bytes:
    """Minimal single-folder cabinet writer (test helper)."""
    names = list(files)
    blob = b"".join(files[n] for n in names)
    blocks = []
    for i in range(0, max(1, len(blob)), 32768):
        chunk = blob[i:i + 32768]
        if mszip:
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            data = b"CK" + c.compress(chunk) + c.flush()
        else:
            data = chunk
        blocks.append((data, len(chunk)))
    header_len, folder_len = 36, 8
    cffiles = b""
    off = 0
    for n in names:
        cffiles += struct.pack("<IIHHHH", len(files[n]), off, 0, 0, 0, 0x20) + n.encode() + b"\x00"
        off += len(files[n])
    coff_files = header_len + folder_len
    coff_data = coff_files + len(cffiles)
    cfdata = b"".join(struct.pack("<IHH", 0, len(d), u) + d for d, u in blocks)
    total = coff_data + len(cfdata)
    hdr = struct.pack("<4sIIIIIBBHHHHH", b"MSCF", 0, total, 0, coff_files, 0, 3, 1, 1, len(names), 0, 0, 0)
    folder = struct.pack("<IHH", coff_data, len(blocks), 1 if mszip else 0)
    return hdr + folder + cffiles + cfdata


class SplitMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_text_roundtrip_exact(self):
        src = self.tmp / "big.py"
        src.write_text("".join(f"print('linie {i} — ăîșțâ')\n" for i in range(20000)), encoding="utf-8")
        res = splitmerge.split_file(src, self.tmp / "parts", 100, "KB", "equal")
        self.assertTrue(res.is_text)
        self.assertGreater(len(res.parts), 3)
        first = res.parts[0].read_text(encoding="utf-8")
        self.assertIn("FISIER MAMA", first)
        self.assertIn("CONTINUA CU", first)
        for p in res.parts:  # every part ends at a line boundary (before footer)
            body = splitmerge.strip_markers(p.read_bytes())
            self.assertTrue(body.endswith(b"\n"))
            body.decode("utf-8")
        files = splitmerge.sort_parts([str(p) for p in reversed(res.parts)])
        self.assertEqual(files, [str(p) for p in res.parts])
        mr = splitmerge.merge_files(files, self.tmp / "out" / "big.py")
        self.assertTrue(mr.verified)
        self.assertEqual((self.tmp / "out" / "big.py").read_bytes(), src.read_bytes())

    def test_binary_roundtrip_and_missing(self):
        src = self.tmp / "blob.bin"
        src.write_bytes(os.urandom(300_000))
        res = splitmerge.split_file(src, self.tmp / "p", 64, "KB", "size")
        self.assertFalse(res.is_text)
        self.assertEqual(len(res.parts), 5)
        mr = splitmerge.merge_files([str(p) for p in res.parts], self.tmp / "o" / "blob.bin")
        self.assertTrue(mr.verified)
        self.assertEqual(mr.missing, [])
        mr2 = splitmerge.merge_files([str(p) for p in res.parts[:-1]], self.tmp / "o" / "blob2.bin")
        self.assertEqual(mr2.missing, [5])
        self.assertFalse(mr2.verified)

    def test_strip_v7_style_markers(self):
        sep = "=" * 72
        v7_header = "\n".join([sep, " FISIER MAMA   : x.txt", " PARTE         : 1 din 2", sep, ""])
        v7_footer = "\n".join(["", "-" * 72, " END PART 1 of 2 — CONTINUA CU: x_part002of002.txt", "-" * 72])
        data = (v7_header + "hello\nworld\n" + v7_footer).encode()
        self.assertEqual(splitmerge.strip_markers(data), b"hello\nworld\n")


class OneNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_one(self) -> bytes:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1500 + b"IEND\xaeB`\x82"
        return (b"\xe4\x52\x5c\x7b" + os.urandom(200) + "Ședință de proiect: verificare linkuri".encode("utf-16-le")
                + b"\x00\x00" + os.urandom(64) + "Meeting notes about SharePoint migration".encode("utf-16-le")
                + b"\x00" * 4 + png + os.urandom(100) + b"Plain utf8 note text here\x00")

    def test_builtin_cab_mszip_and_stored(self):
        files = {"Sectiune 1.one": self._fake_one(), "Open Notebook.onetoc2": b"toc" * 50, "doc.pdf": b"%PDF-1.4" + b"x" * 2000}
        for mszip in (True, False):
            got = onenote.read_cab(make_cab(files, mszip))
            self.assertEqual(got, files)

    def test_process_package(self):
        pkg = self.tmp / "Notebook.onepkg"
        pkg.write_bytes(make_cab({"Sectiune 1.one": self._fake_one(), "Open Notebook.onetoc2": b"toc" * 50,
                                  "anexa.pdf": b"%PDF" + b"y" * 3000}))
        res = onenote.process(pkg, self.tmp / "out", onenote.ExtractOptions())
        self.assertTrue(res.ok)
        self.assertEqual(res.method, "built-in CAB")
        self.assertEqual(res.sections, 1)
        text = res.texts[0].read_text(encoding="utf-8")
        self.assertIn("Ședință de proiect: verificare linkuri", text)
        self.assertIn("Meeting notes about SharePoint migration", text)
        self.assertIn("Plain utf8 note text here", text)
        self.assertEqual(len([i for i in res.images if i.suffix == ".png"]), 1)
        self.assertEqual([a.name for a in res.attachments], ["anexa.pdf"])
        self.assertTrue(res.markdown.exists())
        self.assertTrue(res.report.exists())

    def test_plain_one_section(self):
        one = self.tmp / "Solo.one"
        one.write_bytes(self._fake_one())
        res = onenote.process(one, self.tmp / "o2", onenote.ExtractOptions())
        self.assertTrue(res.ok)
        self.assertIn("Meeting notes", res.texts[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
