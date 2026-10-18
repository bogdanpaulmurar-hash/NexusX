# -*- coding: utf-8 -*-
"""Headless smoke test of the complete GUI wiring (uses tests/fake_tk when Tk is unavailable)."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

USE_FAKE = True
try:  # a real Tk with a display would also work, but CI usually has neither
    import tkinter  # noqa: F401
    USE_FAKE = not os.environ.get("DISPLAY") and sys.platform != "win32"
except Exception:
    USE_FAKE = True
if USE_FAKE:
    import fake_tk
    fake_tk.install()


class UISmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp())
        os.environ["HOME"] = str(cls.home)
        os.environ["USERPROFILE"] = str(cls.home)
        for m in [m for m in sys.modules if m.startswith("nexusx")]:
            del sys.modules[m]
        from nexusx.ui.app import NexusXApp
        cls.app = NexusXApp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def pump(self, seconds=3.0):
        end = time.time() + seconds
        while time.time() < end:
            self.app._pump()
            if USE_FAKE:
                self.app._after.clear()
            time.sleep(0.05)

    def test_build_and_workflows(self):
        app = self.app
        for name in ("tab_code", "tab_manager", "tab_linkmap", "tab_links", "tab_sources", "tab_web", "tab_settings", "tab_log", "tab_about", "tab_splitmerge", "tab_onenote"):
            self.assertTrue(hasattr(app, name), name)
        # code export workflow
        proj = self.home / "proj"
        (proj / "pkg").mkdir(parents=True)
        (proj / "pkg" / "main.py").write_text('import os\nURL="https://example.org/a"\nTOKEN="abcdefgh12345"\n')
        app.tab_code.folder.set(str(proj))
        app.tab_code.out_dir.set(str(self.home / "out"))
        app.tab_code.do_scan()
        self.pump(2)
        self.assertEqual(len(app.tab_code.files_all), 1)
        app.tab_code.do_export(zip_it=True)
        self.pump(2)
        self.assertTrue(app.tab_code.last_parts and app.tab_code.last_parts[0].suffix == ".zip")
        self.assertTrue((self.home / "out" / "NexusX_Export.txt").exists())
        self.assertNotIn("abcdefgh12345", (self.home / "out" / "NexusX_Export.txt").read_text(encoding="utf-8"))
        # link map + push urls to checker
        app.tab_linkmap.run(projects=[("proj", proj)])
        self.pump(2)
        self.assertIsNotNone(app.tab_linkmap.result)
        app.tab_links.add_from_linkmap(app.tab_linkmap.result)
        self.assertTrue(any(r.url == "https://example.org/a" for r in app.tab_links.records))
        # links: records, filter, export all
        app.tab_links.filter.set("✗ Erori")
        app.tab_links.refresh_table()
        app.tab_links.filter.set("Toate")
        app.tab_links.refresh_table()
        app.report_dir.set(str(self.home / "reports"))
        paths = app.tab_links.export_all()
        self.assertEqual(len(paths), 6)
        # manager
        app.export_pairs[:] = [{"name": "proj", "source": str(proj), "export": str(self.home / "mgr")}]
        app.tab_manager.refresh()
        app.tab_manager.sel_all.set(True)
        app.tab_manager.run()
        self.pump(2)
        self.assertTrue(list((self.home / "mgr").glob("proj_*.txt")))
        # sources + settings + email (eml method, no external client in CI)
        app.tab_sources.refresh()
        app.cfg.set_email(method="eml")
        app.tab_links.compose_email()
        self.pump(2)
        self.assertTrue(list((self.home / "reports").glob("*.eml")))
        # split & merge + onenote tabs
        big = self.home / "big.txt"
        big.write_text("".join(f"line {i}\n" for i in range(30000)))
        sm = app.tab_splitmerge
        sm.split_file.set(str(big))
        sm.split_out.set(str(self.home / "parts"))
        sm.split_size.set("50")
        sm.split_unit.set("KB")
        sm.update_info()
        sm.do_split()
        self.pump(2)
        parts = sorted((self.home / "parts").glob("big_part*"))
        self.assertGreater(len(parts), 2)
        sm.merge_files[:] = [str(p) for p in reversed(parts)]
        sm.sort_parts()
        sm.merge_out.set(str(self.home / "merged"))
        sm.merge_name.set("big")
        sm.do_merge()
        self.pump(2)
        self.assertEqual((self.home / "merged" / "big.txt").read_bytes(), big.read_bytes())
        on = app.tab_onenote
        one = self.home / "Note.one"
        one.write_bytes(b"\x00" * 50 + "Hello OneNote world text".encode("utf-16-le") + b"\x00" * 50)
        on.files[:] = [str(one)]
        on.out_dir.set(str(self.home / "on"))
        on.o_open.set(False)
        on.extract()
        self.pump(2)
        self.assertTrue(on.results and on.results[0].ok)
        on.to_code_export()
        self.pump(1)
        app.tab_settings._persist_exts()
        app.quick_email()
        self.pump(1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
