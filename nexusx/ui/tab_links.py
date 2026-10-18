# -*- coding: utf-8 -*-
"""Tabs: 🔗 Link Checker (ULaE Analysis Workspace) and 📂 SharePoint & Sources Manager."""
from __future__ import annotations

import json
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from .. import mailer
from ..links import reporter
from ..links.browser import BrowserEngine, playwright_available
from ..links.checker import check_many, http_probe
from ..links.crawler import expand_page
from ..links.extractor import SUPPORTED_EXTENSIONS, collect_files, extract_from_file
from ..links.models import STATUS_CHOICES, LinkRecord, status_group
from ..links.sources import SourcesCatalog
from .theme import STATUS_TAG_COLORS
from .widgets import open_path

FILTERS = {"Toate": None, "✗ Erori": "broken", "⚠ Auth": "auth", "✓ OK": "ok", "⬇ Download": "download",
           "? Avertizari": "warn", "… Neverificate": "pending"}


class LinksTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        cfg = app.cfg
        self.files: List[Path] = []
        self.records: List[LinkRecord] = []
        self._iid: Dict[int, str] = {}
        self._by_iid: Dict[str, LinkRecord] = {}
        self.running = False
        self.stop_requested = False
        self.timeout = tk.IntVar(value=int(cfg.get("link_timeout", 20)))
        self.workers = tk.IntVar(value=int(cfg.get("link_workers", 8)))
        self.headless = tk.BooleanVar(value=bool(cfg.get("browser_headless", False)))
        self.keep_browser = tk.BooleanVar(value=bool(cfg.get("keep_browser", True)))
        self.channel = tk.StringVar(value=cfg.get("browser_channel", "chromium"))
        self.manual_url = tk.StringVar()
        self.crawl_depth = tk.IntVar(value=1)
        self.same_domain = tk.BooleanVar(value=bool(cfg.get("crawl_same_domain", True)))
        self.filter = tk.StringVar(value="Toate")
        self.search = tk.StringVar()
        self.only_problems_mail = tk.BooleanVar(value=False)
        self.engine = BrowserEngine(channel=self.channel.get())
        self._build(frame)

    # ── layout ──
    def _build(self, p) -> None:
        ui, T = self.ui, self.T
        r1 = tk.Frame(p, bg=T["BG2"])
        r1.pack(fill="x", padx=10, pady=(8, 4))
        ui.btn(r1, "📁 Adauga Folder", self.add_folder).pack(side="left", padx=2)
        ui.btn(r1, "📄 Adauga Fisiere", self.add_files).pack(side="left", padx=2)
        ui.btn(r1, "📥 Din Surse SharePoint", self.import_sources, primary=True).pack(side="left", padx=2)
        ui.btn(r1, "🧹 Goleste fisiere", self.clear_files).pack(side="left", padx=2)
        ui.sep_v(r1).pack(side="left", fill="y", padx=8, pady=4)
        ui.btn(r1, "⚡ SCAN HTTP", self.scan_http, primary=True).pack(side="left", padx=2)
        ui.btn(r1, "🌐 BROWSER VERIFY", self.browser_verify_all, primary=True).pack(side="left", padx=2)
        ui.btn(r1, "🔑 SSO LOGIN (o data)", self.sso_login).pack(side="left", padx=2)
        ui.btn(r1, "🔁 Re-verifica problemele", self.recheck_problems).pack(side="left", padx=2)
        ui.btn(r1, "⏹ STOP", self.stop, danger=True).pack(side="left", padx=2)
        ui.btn(r1, "🔄 Reset", self.reset).pack(side="left", padx=2)
        ui.sep_v(r1).pack(side="left", fill="y", padx=8, pady=4)
        ui.btn(r1, "Select All", self.select_all).pack(side="left", padx=2)
        ui.btn(r1, "🗑 Sterge", self.delete_selected, danger=True).pack(side="left", padx=2)
        ui.btn(r1, "✏ Editeaza", self.edit_selected).pack(side="left", padx=2)

        r2 = tk.Frame(p, bg=T["BG3"])
        r2.pack(fill="x", padx=10, pady=3, ipady=3)
        ui.label(r2, "Timeout (s):").pack(side="left", padx=(10, 4))
        tk.Spinbox(r2, from_=5, to=120, textvariable=self.timeout, width=4, bg=T["BG2"], fg=T["TEXT1"],
                   buttonbackground=T["BG3"], relief="flat").pack(side="left")
        ui.label(r2, "Paralel:").pack(side="left", padx=(10, 4))
        tk.Spinbox(r2, from_=1, to=32, textvariable=self.workers, width=3, bg=T["BG2"], fg=T["TEXT1"],
                   buttonbackground=T["BG3"], relief="flat").pack(side="left")
        ui.chk(r2, "Headless (fundal)", self.headless, "Browser invizibil. Necesita un SSO LOGIN facut o data.").pack(side="left", padx=(12, 4))
        ui.chk(r2, "Pastreaza browserul la retry", self.keep_browser).pack(side="left", padx=4)
        ui.label(r2, "Browser:").pack(side="left", padx=(10, 4))
        cb = ttk.Combobox(r2, textvariable=self.channel, values=["chromium", "msedge", "chrome"], state="readonly", width=9)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._save_prefs())
        ui.tooltip(cb, "msedge = Microsoft Edge cu identitatea dispozitivului (SSO mai usor in reteaua companiei)")
        ui.label(r2, "URL direct:").pack(side="left", padx=(14, 4))
        en = ui.entry(r2, self.manual_url, width=40)
        en.pack(side="left", fill="x", expand=True, padx=4)
        en.bind("<Return>", lambda e: self.manual_probe())
        ui.btn(r2, "Probe", self.manual_probe, padx=8, pady=3).pack(side="left", padx=2)
        ui.btn(r2, "Browser", self.manual_browser, padx=8, pady=3).pack(side="left", padx=2)
        ui.btn(r2, "🕸 Extrage linkurile paginii", self.crawl, padx=8, pady=3, fg=T["ORANGE"]).pack(side="left", padx=2)
        ui.label(r2, "nivel:").pack(side="left")
        tk.Spinbox(r2, from_=1, to=3, textvariable=self.crawl_depth, width=2, bg=T["BG2"], fg=T["TEXT1"], relief="flat").pack(side="left")
        ui.chk(r2, "acelasi domeniu", self.same_domain).pack(side="left", padx=4)

        r3 = tk.Frame(p, bg=T["BG2"])
        r3.pack(fill="x", padx=10, pady=2)
        self.lbl_files = ui.label(r3, "Niciun fisier incarcat", fg=T["TEXT3"])
        self.lbl_files.pack(side="left")
        ui.label(r3, "   Filtru:").pack(side="left")
        fc = ttk.Combobox(r3, textvariable=self.filter, values=list(FILTERS), state="readonly", width=14)
        fc.pack(side="left", padx=4)
        fc.bind("<<ComboboxSelected>>", lambda e: self.refresh_table())
        ui.label(r3, "Cauta:").pack(side="left", padx=(8, 2))
        se = ui.entry(r3, self.search, width=26)
        se.pack(side="left")
        se.bind("<KeyRelease>", lambda e: self.refresh_table())
        self.lbl_stats = tk.Label(r3, text="Total: 0", bg=T["BG2"], fg=T["TEAL"], font=("Segoe UI", 9, "bold"))
        self.lbl_stats.pack(side="right")
        self.prog = tk.DoubleVar(value=0)
        ttk.Progressbar(p, variable=self.prog, maximum=100).pack(fill="x", padx=10, pady=3)

        tf = tk.Frame(p, bg=T["BG2"])
        tf.pack(fill="both", expand=True, padx=6)
        self.tree = ui.tree(tf, [("file", "Fisier sursa", 160, "w"), ("location", "Locatie § Sectiune / Context", 300, "w"),
                                 ("url", "Link tinta", 400, "w"), ("status", "Status", 150, "w"), ("http", "HTTP", 60, "center"),
                                 ("evidence", "Dovada / Titlu / Eroare", 300, "w"), ("notes", "Observatiile mele ✏", 180, "w")], height=18)
        for g, col in STATUS_TAG_COLORS.items():
            self.tree.tag_configure(g, foreground=T[col])
        self.tree.bind("<Button-3>", self.context_menu)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Delete>", lambda e: self.delete_selected())
        self.tree.bind("<Control-a>", lambda e: self.select_all())

        ex = tk.Frame(p, bg=T["BG2"])
        ex.pack(fill="x", padx=10, pady=(4, 8))
        ui.label(ex, "Export:", fg=T["TEXT1"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        for text, ext in (("📊 Excel", ".xlsx"), ("📄 Word", ".docx"), ("📑 CSV", ".csv"), ("📝 MD", ".md"),
                          ("💾 JSON", ".json"), ("🌐 HTML", ".html")):
            ui.btn(ex, text, lambda e=ext: self.export(e), padx=8).pack(side="left", padx=2)
        ui.btn(ex, "⬇ Toate", self.export_all, padx=8).pack(side="left", padx=2)
        ui.label(ex, "Destinatie:").pack(side="left", padx=(12, 4))
        ui.entry(ex, self.app.report_dir, width=34).pack(side="left")
        ui.btn(ex, "…", lambda: self.app.report_dir.set(filedialog.askdirectory() or self.app.report_dir.get()), padx=6).pack(side="left", padx=2)
        ui.btn(ex, "📂", lambda: open_path(self.app.ensure_report_dir()), padx=6).pack(side="left", padx=2)
        ui.sep_v(ex).pack(side="left", fill="y", padx=10, pady=4)
        self.btn_email = ui.btn(ex, "✉ TRIMITE EMAIL CU RAPORTUL", self.compose_email, primary=True, padx=16)
        self.btn_email.pack(side="left", padx=4)
        ui.chk(ex, "doar problemele in tabel", self.only_problems_mail, "Tabelul din email contine doar linkurile cu probleme;\nrapoartele atasate raman complete.").pack(side="left", padx=4)

    def _save_prefs(self) -> None:
        self.app.cfg.set("link_timeout", int(self.timeout.get()), save=False)
        self.app.cfg.set("link_workers", int(self.workers.get()), save=False)
        self.app.cfg.set("browser_headless", bool(self.headless.get()), save=False)
        self.app.cfg.set("keep_browser", bool(self.keep_browser.get()), save=False)
        self.app.cfg.set("browser_channel", self.channel.get())
        self.engine.channel = self.channel.get()

    # ── table ──
    def _row(self, r: LinkRecord):
        return (r.file, r.format_location_display(), r.url, r.status, r.http_code,
                (r.evidence or r.error or "")[:300], r.notes or "")

    def _visible(self, r: LinkRecord) -> bool:
        g = FILTERS.get(self.filter.get())
        if g and status_group(r.status) != g:
            return False
        q = self.search.get().strip().lower()
        return not q or q in f"{r.file} {r.url} {r.location} {r.section} {r.evidence} {r.notes} {r.status}".lower()

    def refresh_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._iid.clear()
        self._by_iid.clear()
        for r in self.records:
            if self._visible(r):
                iid = self.tree.insert("", "end", values=self._row(r), tags=(status_group(r.status),))
                self._iid[id(r)] = iid
                self._by_iid[iid] = r
        self.update_stats()

    def update_row(self, r: LinkRecord) -> None:
        iid = self._iid.get(id(r))
        if iid and self.tree.exists(iid):
            self.tree.item(iid, values=self._row(r), tags=(status_group(r.status),))
        self.update_stats()

    def update_stats(self) -> None:
        s = reporter.summarize(self.records)
        self.lbl_stats.config(text=f"Total: {s['total']} | ✓ OK: {s['ok']} | ✗ Erori: {s['broken']} | ⚠ Auth: {s['auth']} | "
                                   f"⬇ Download: {s['download']} | ? {s['warn']} | … {s['pending']}")
        self.lbl_files.config(text=f"{len(self.files)} documente | {len(self.records)} linkuri in workspace")

    def add_records(self, recs: List[LinkRecord], label: str = "") -> int:
        have = {(r.path, r.url) for r in self.records}
        added = 0
        for r in recs:
            if (r.path, r.url) not in have:
                self.records.append(r)
                have.add((r.path, r.url))
                added += 1
        self.refresh_table()
        if label:
            self.app.log(f"[LINKS] {added} linkuri adaugate din {label}.", "ok")
        return added

    def add_urls(self, urls: List[str], origin: str) -> None:
        recs = [LinkRecord(file=f"[{origin}]", path=origin, location=origin, url=u, source=origin) for u in urls]
        n = self.add_records(recs, origin)
        self.app.select_tab("links")
        self.app.set_status(f"{n} URL-uri adaugate in Link Checker.")

    def add_from_linkmap(self, res) -> None:
        recs = []
        for url, e in res.unique_urls():
            recs.append(LinkRecord(file=f"[code] {e.project}", path=str(e.file), location=f"{e.file}:{e.line}", url=url,
                                   context=e.detail, source="Code (Link Map)"))
        n = self.add_records(recs, "cod (Link Map)")
        self.app.select_tab("links")
        if messagebox.askyesno("Link Checker", f"{n} URL-uri din cod adaugate.\nLe verific acum (SCAN HTTP)?"):
            self.scan_http()

    # ── files ──
    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Alege folderul cu documente")
        if d:
            new = collect_files(Path(d))
            self.files = list(dict.fromkeys(self.files + new))
            self.update_stats()
            self.app.log(f"[INFO] Folder adaugat: {d} ({len(new)} fisiere suportate)")

    def add_files(self) -> None:
        pats = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        chosen = filedialog.askopenfilenames(title="Alege documente", filetypes=[("Documente & text", pats), ("Toate", "*.*")])
        if chosen:
            new = [Path(c) for c in chosen if Path(c).suffix.lower() in SUPPORTED_EXTENSIONS]
            self.files = list(dict.fromkeys(self.files + new))
            self.update_stats()
            self.app.log(f"[INFO] {len(new)} documente adaugate")

    def clear_files(self) -> None:
        self.files = []
        self.update_stats()

    def reset(self) -> None:
        self.records = []
        self.prog.set(0)
        self.refresh_table()
        self.app.set_status("Workspace resetat.")

    def stop(self) -> None:
        self.stop_requested = True
        self.app.log("[STOP] Oprire ceruta — se finalizeaza task-ul curent…", "warn")

    def import_sources(self) -> None:
        self.app.tab_sources.send_all()

    # ── checking ──
    def _begin(self, text: str) -> bool:
        if self.running:
            messagebox.showinfo("Ocupat", "O verificare ruleaza deja. Asteapta sau apasa STOP.")
            return False
        self._save_prefs()
        self.running = True
        self.stop_requested = False
        self.btn_email.configure(state="disabled")
        self.app.set_status(text, 0)
        self.prog.set(0)
        return True

    def _end(self, text: str) -> None:
        self.running = False
        self.btn_email.configure(state="normal")
        self.app.set_status(text, 100)
        self.prog.set(100)
        self.refresh_table()
        self.app.log(f"[DONE] {text}", "ok")
        s = reporter.summarize(self.records)
        self.app.notify("Link Checker", f"{text}: ✓{s['ok']} ✗{s['broken']} ⚠{s['auth']}")

    def _progress(self, r: LinkRecord, i: int, n: int) -> None:
        self.app.call(self.update_row, r)
        self.app.call(self.prog.set, i / max(1, n) * 100)
        self.app.call(self.app.set_status, f"Verificare {i}/{n} — {r.status}: {r.url[:80]}", i / max(1, n) * 100)

    def scan_http(self) -> None:
        if not self.files and not self.records:
            messagebox.showwarning("Nimic de verificat", "Adauga documente / un folder sau importa din Surse SharePoint.")
            return
        if not self._begin("Extragere linkuri + verificare HTTP…"):
            return
        timeout, workers = int(self.timeout.get()), int(self.workers.get())
        retries, frag = int(self.app.cfg.get("link_retries", 1)), bool(self.app.cfg.get("check_fragments", True))

        def work():
            new: List[LinkRecord] = []
            for f in list(self.files):
                if self.stop_requested:
                    break
                self.app.call(self.app.log, f"[PARSE] {f.name}")
                try:
                    ex = extract_from_file(f)
                    new.extend(ex)
                    self.app.call(self.app.log, f"   → {len(ex)} linkuri unice in {f.name}")
                except Exception as e:  # noqa: BLE001
                    self.app.call(self.app.log, f"[ERROR] {f.name}: {e}", "error")
            if new:
                done = threading.Event()
                self.app.call(lambda: (self.add_records(new), done.set()))
                done.wait()
            targets = [r for r in self.records if r.status in ("Not checked", "") or not r.url.startswith("#")]
            self.app.call(self.app.log, f"[HTTP] {len(targets)} linkuri, {workers} in paralel, timeout {timeout}s")
            check_many(targets, timeout=timeout, workers=workers, retries=retries, check_fragment=frag,
                       on_progress=self._progress, should_stop=lambda: self.stop_requested)
            self.app.call(self._end, "Oprit de utilizator" if self.stop_requested else "Scan HTTP finalizat")
        self.app.run_bg(work, name="scan-http")

    def recheck_problems(self) -> None:
        bad = [r for r in self.records if status_group(r.status) in ("broken", "warn", "pending") and not r.url.startswith("#")]
        if not bad:
            messagebox.showinfo("Re-verificare", "Nu exista linkuri cu probleme.")
            return
        if not self._begin(f"Re-verificare {len(bad)} linkuri…"):
            return

        def work():
            check_many(bad, timeout=int(self.timeout.get()), workers=int(self.workers.get()), retries=2,
                       on_progress=self._progress, should_stop=lambda: self.stop_requested)
            self.app.call(self._end, "Re-verificare finalizata")
        self.app.run_bg(work, name="recheck")

    def browser_verify_all(self) -> None:
        if not self.records:
            messagebox.showwarning("Fara linkuri", "Ruleaza mai intai SCAN HTTP sau adauga linkuri.")
            return
        if not playwright_available():
            messagebox.showerror("Playwright", "Playwright nu este instalat.\nSetari → Dependinte → Instaleaza (include 'playwright install chromium').")
            return
        targets = []
        for r in self.records:
            if not r.is_web or ("Download" in r.status and r.download_filename):
                continue
            if r.status in ("OK", "Browser OK") and r.evidence and not any(k in r.evidence.lower() for k in ("sign in", "login", "redirecting")):
                continue
            targets.append(r)
        if not targets:
            targets = [r for r in self.records if r.is_web]
        headless = self.headless.get()
        if not self._begin(f"Verificare in browser ({'headless' if headless else 'vizibil'}) — {len(targets)} linkuri…"):
            return

        def work():
            self.engine.verify_batch(targets, timeout_sec=int(self.timeout.get()), headless=headless,
                                     on_log=lambda m: self.app.call(self.app.log, m), on_progress=self._progress,
                                     should_stop=lambda: self.stop_requested)
            self.app.call(self._end, "Verificare browser oprita" if self.stop_requested else "Verificare browser finalizata")
        self.app.run_bg(work, name="browser")

    def sso_login(self) -> None:
        if self.running:
            messagebox.showinfo("Ocupat", "O verificare ruleaza. Asteapta sau apasa STOP.")
            return
        if not playwright_available():
            messagebox.showerror("Playwright", "Playwright nu este instalat (Setari → Dependinte).")
            return
        target = next((r.url for r in self.records if "siemens" in r.url.lower() and r.is_web), "https://siemens.sharepoint.com")
        self._begin("Astept login SSO in browser…")

        def work():
            ok = self.engine.authenticate_session(target, on_log=lambda m: self.app.call(self.app.log, m))
            self.app.call(self._end, "SSO autentificat — poti rula BROWSER VERIFY in fundal" if ok else "Fereastra SSO inchisa")
            if ok:
                self.app.call(messagebox.showinfo, "SSO", "Autentificare reusita!\nSesiunea e salvata; BROWSER VERIFY poate rula headless.")
        self.app.run_bg(work, name="sso")

    def _manual_record(self) -> Optional[LinkRecord]:
        u = self.manual_url.get().strip()
        if not u:
            return None
        existing = next((r for r in self.records if r.url == u and r.file == "[Direct Input]"), None)
        if existing:
            return existing
        r = LinkRecord(file="[Direct Input]", path="[Direct Input]", location="Manual Entry", url=u, source="Manual")
        self.records.append(r)
        self.refresh_table()
        return r

    def manual_probe(self) -> None:
        r = self._manual_record()
        if not r:
            return

        def work():
            http_probe(r, timeout=int(self.timeout.get()))
            self.app.call(self.update_row, r)
            self.app.call(self.app.log, f"[PROBE] {r.status} | {r.url} | {r.evidence or r.error}")
        self.app.run_bg(work, name="probe")

    def manual_browser(self) -> None:
        r = self._manual_record()
        if r:
            self._single_browser(r, self.headless.get())

    def _single_browser(self, r: LinkRecord, headless: bool) -> None:
        self._save_prefs()

        def work():
            self.engine.verify_single(r, timeout_sec=int(self.timeout.get()), headless=headless,
                                      keep_browser=self.keep_browser.get(), on_log=lambda m: self.app.call(self.app.log, m))
            self.app.call(self.update_row, r)
        self.app.run_bg(work, name="browser-single")

    def crawl(self) -> None:
        u = self.manual_url.get().strip()
        if not u:
            messagebox.showinfo("Extrage linkuri", "Scrie URL-ul paginii (portal, wiki, SharePoint) in campul 'URL direct'.")
            return
        if not self._begin(f"Extrag linkurile din {u}…"):
            return
        engine = self.engine if playwright_available() else None

        def work():
            recs = expand_page(u, timeout=int(self.timeout.get()), same_domain=self.same_domain.get(),
                               max_links=int(self.app.cfg.get("crawl_max_links", 300)), depth=int(self.crawl_depth.get()),
                               browser=engine, on_log=lambda m: self.app.call(self.app.log, m),
                               should_stop=lambda: self.stop_requested)
            done = threading.Event()
            self.app.call(lambda: (self.add_records(recs, f"pagina {u}"), done.set()))
            done.wait()
            if recs and not self.stop_requested:
                check_many(recs, timeout=int(self.timeout.get()), workers=int(self.workers.get()),
                           on_progress=self._progress, should_stop=lambda: self.stop_requested)
            self.app.call(self._end, f"Pagina expandata: {len(recs)} linkuri verificate")
        self.app.run_bg(work, name="crawl")

    # ── selection / editing ──
    def selected(self) -> List[LinkRecord]:
        return [self._by_iid[i] for i in self.tree.selection() if i in self._by_iid]

    def select_all(self) -> None:
        self.tree.selection_set(self.tree.get_children())

    def delete_selected(self) -> None:
        recs = self.selected()
        if not recs:
            messagebox.showinfo("Sterge", "Niciun rand selectat (Ctrl/Shift+Click pentru selectie multipla).")
            return
        if messagebox.askyesno("Sterge", f"Stergi {len(recs)} rand(uri) din workspace?"):
            ids = {id(r) for r in recs}
            self.records = [r for r in self.records if id(r) not in ids]
            self.refresh_table()

    def open_selected(self) -> None:
        recs = self.selected()
        if not recs:
            return
        r = recs[0]
        if r.url.startswith("#"):
            if Path(r.path).exists():
                open_path(r.path)
            return
        target = r.final_url or r.url
        if target.lower().startswith("www."):
            target = "https://" + target
        webbrowser.open(target)

    def context_menu(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        recs = self.selected()
        if not recs:
            return
        T = self.T
        m = tk.Menu(self.app, tearoff=0, bg=T["BG3"], fg=T["TEXT1"], activebackground=T["ACCENT"])
        m.add_command(label=f"✏ Editeaza / Observatii ({len(recs)})", command=self.edit_selected)
        m.add_command(label=f"🗑 Sterge ({len(recs)})", command=self.delete_selected)
        m.add_separator()
        if len(recs) == 1:
            r = recs[0]
            m.add_command(label="🌐 Deschide in browserul implicit", command=self.open_selected)
            if Path(r.path).exists():
                m.add_command(label="📄 Deschide documentul sursa", command=lambda: open_path(r.path))
            m.add_command(label="📋 Copiaza URL", command=lambda: (self.app.clipboard_clear(), self.app.clipboard_append(r.url)))
            m.add_command(label="🔍 Detalii complete (JSON)", command=lambda: self._details(r))
            m.add_separator()
            m.add_command(label="⚡ Re-verifica HTTP", command=lambda: self.app.run_bg(
                lambda: (http_probe(r, timeout=int(self.timeout.get())), self.app.call(self.update_row, r))))
            m.add_command(label="🚀 Re-verifica in browser headless", command=lambda: self._single_browser(r, True))
            m.add_command(label="🔐 Deschide in browser vizibil (SSO)", command=lambda: self._single_browser(r, False))
            if r.is_web:
                m.add_command(label="🕸 Extrage linkurile acestei pagini", command=lambda: (self.manual_url.set(r.final_url or r.url), self.crawl()))
        else:
            m.add_command(label="📋 Copiaza toate URL-urile selectate",
                          command=lambda: (self.app.clipboard_clear(), self.app.clipboard_append("\n".join(r.url for r in recs))))
            m.add_command(label="⚡ Re-verifica selectia (HTTP)", command=lambda: self._recheck(recs))
        m.tk_popup(event.x_root, event.y_root)

    def _recheck(self, recs: List[LinkRecord]) -> None:
        if not self._begin(f"Re-verificare {len(recs)}…"):
            return

        def work():
            check_many(recs, timeout=int(self.timeout.get()), workers=int(self.workers.get()), on_progress=self._progress,
                       should_stop=lambda: self.stop_requested)
            self.app.call(self._end, "Re-verificare selectie finalizata")
        self.app.run_bg(work)

    def _details(self, r: LinkRecord) -> None:
        T = self.T
        dlg = tk.Toplevel(self.app)
        dlg.title("Detalii link")
        dlg.geometry("760x560")
        dlg.configure(bg=T["BG1"])
        fr, txt = self.ui.scrolled_text(dlg, height=30)
        fr.pack(fill="both", expand=True, padx=8, pady=8)
        txt.configure(state="normal", wrap="word")
        txt.insert("1.0", json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
        txt.configure(state="disabled")

    def edit_selected(self) -> None:
        recs = self.selected()
        if not recs:
            messagebox.showinfo("Editeaza", "Selecteaza unul sau mai multe randuri.")
            return
        T, ui = self.T, self.ui
        multi = len(recs) > 1
        dlg = tk.Toplevel(self.app)
        dlg.title(f"Editeaza {len(recs)} randuri" if multi else f"Editeaza: {recs[0].url[:60]}")
        dlg.geometry("620x400")
        dlg.configure(bg=T["BG2"])
        dlg.transient(self.app)
        dlg.grab_set()
        tk.Label(dlg, text=f"Editare in lot: {len(recs)} linkuri" if multi else recs[0].url, bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold"), wraplength=580, justify="left").pack(anchor="w", padx=18, pady=(14, 6))
        row = tk.Frame(dlg, bg=T["BG2"])
        row.pack(fill="x", padx=18, pady=6)
        ui.label(row, "Status verificare:", width=18, anchor="w").pack(side="left")
        opts = (["(Neschimbat)"] if multi else []) + STATUS_CHOICES
        sv = tk.StringVar(value=opts[0] if multi else recs[0].status)
        ttk.Combobox(row, textvariable=sv, values=opts).pack(side="left", fill="x", expand=True)
        row2 = tk.Frame(dlg, bg=T["BG2"])
        row2.pack(fill="x", padx=18, pady=6)
        ui.label(row2, "Dovada / Titlu:", width=18, anchor="w").pack(side="left")
        ev = tk.StringVar(value="" if multi else recs[0].evidence)
        ui.entry(row2, ev).pack(side="left", fill="x", expand=True)
        ui.label(dlg, "Observatiile mele:").pack(anchor="w", padx=18, pady=(8, 2))
        notes = tk.Text(dlg, bg=T["BG1"], fg=T["TEXT1"], insertbackground=T["TEXT1"], height=6, relief="flat", padx=8, pady=8)
        notes.pack(fill="both", expand=True, padx=18, pady=4)
        if not multi:
            notes.insert("1.0", recs[0].notes or "")

        def save():
            s, e, n = sv.get().strip(), ev.get().strip(), notes.get("1.0", "end").strip()
            for r in recs:
                if s and s != "(Neschimbat)":
                    r.status = s
                if e or not multi:
                    r.evidence = e or r.evidence
                if n or not multi:
                    r.notes = n
            self.refresh_table()
            self.app.log(f"[EDIT] {len(recs)} rand(uri) actualizate.")
            dlg.destroy()
        br = tk.Frame(dlg, bg=T["BG2"])
        br.pack(fill="x", padx=18, pady=(8, 14))
        ui.btn(br, "Salveaza", save, primary=True).pack(side="right", padx=4)
        ui.btn(br, "Anuleaza", dlg.destroy).pack(side="right", padx=4)

    # ── export / email ──
    def export(self, ext: str) -> None:
        if not self.records:
            messagebox.showinfo("Export", "Nu exista linkuri de exportat.")
            return
        out = self.app.ensure_report_dir() / f"{reporter.REPORT_STEM}{ext}"
        try:
            reporter.export_records(self.records, out, ext)
            self.app.log(f"[EXPORT] Raport salvat: {out}", "ok")
            self.app.last_outputs = [out]
            if messagebox.askyesno("Export finalizat", f"Raport salvat:\n{out}\n\nIl deschid acum?"):
                open_path(out)
        except Exception as e:  # noqa: BLE001
            self.app.log(f"[EXPORT ERROR] {e}", "error")
            messagebox.showerror("Export esuat", str(e))

    def export_all(self) -> List[Path]:
        if not self.records:
            messagebox.showinfo("Export", "Nu exista linkuri de exportat.")
            return []
        paths = reporter.export_all(self.records, self.app.ensure_report_dir(),
                                    formats=(".xlsx", ".docx", ".csv", ".md", ".json", ".html"))
        self.app.last_outputs = paths
        self.app.log(f"[EXPORT] {len(paths)} rapoarte salvate in {self.app.report_dir.get()}", "ok")
        return paths

    def compose_email(self) -> None:
        """One click: export every report format, build the styled HTML table, send/open the mail."""
        if not self.records:
            messagebox.showinfo("Email", "Nu exista linkuri in workspace. Ruleaza mai intai SCAN HTTP.")
            return
        if self.running:
            messagebox.showinfo("Ocupat", "Asteapta finalizarea verificarii.")
            return
        attachments = reporter.export_all(self.records, self.app.ensure_report_dir())
        e = self.app.cfg.email()
        body = mailer.build_links_html(self.records, self.app.cfg.get("language_email", "de"),
                                       e.get("signature") or mailer.default_signature(), only_problems=self.only_problems_mail.get())
        self.app.send_mail(e.get("subject_links") or "NexusX Link Report", body, attachments, "Email raport linkuri")


class SourcesTab:
    """📂 SharePoint & Team Sources Manager (ULaE)."""

    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.catalog = SourcesCatalog()
        self._build(frame)

    def _build(self, p) -> None:
        ui, T = self.ui, self.T
        top = tk.Frame(p, bg=T["BG3"])
        top.pack(fill="x", padx=12, pady=(10, 6), ipady=6)
        ui.label(top, "📂 SharePoint & Team Sources", fg=T["ACCENT"], font=("Segoe UI", 12, "bold")).pack(side="left", padx=12)
        ui.label(top, "Documente SharePoint + fisierele lor sincronizate local (OneDrive). Fisierul local permite extragerea linkurilor interne.",
                 fg=T["TEXT3"]).pack(side="left", padx=10)
        bar = tk.Frame(p, bg=T["BG2"])
        bar.pack(fill="x", padx=12, pady=4)
        for text, cmd, kw in (("➕ Adauga", self.add, {"primary": True}), ("✏ Editeaza", self.edit, {}),
                              ("🗑 Sterge", self.delete, {"danger": True}), ("🌐 Deschide link", self.open_web, {}),
                              ("📁 Deschide fisier local", self.open_local, {}), ("📊 Deschide Excel catalog", self.open_excel, {}),
                              ("🔄 Reincarca", self.reload, {}), ("🚀 TRIMITE TOT IN LINK CHECKER", self.send_all, {"primary": True}),
                              ("➡ Trimite selectia", self.send_selected, {})):
            ui.btn(bar, text, cmd, **kw).pack(side="left", padx=3)
        tf = tk.Frame(p, bg=T["BG2"])
        tf.pack(fill="both", expand=True, padx=8, pady=6)
        self.tree = ui.tree(tf, [("name", "Document / Resursa", 230, "w"), ("type", "Tip", 130, "w"),
                                 ("url", "URL SharePoint / Web", 440, "w"), ("local", "Fisier local OneDrive", 380, "w"),
                                 ("desc", "Note", 220, "w")], height=20, selectmode="extended")
        self.tree.tag_configure("missing", foreground=T["YELLOW"])
        self.tree.bind("<Double-1>", lambda e: self.edit())
        ui.label(p, f"Catalog: {self.catalog.excel_path}", fg=T["TEXT3"], font=("Segoe UI", 8)).pack(anchor="w", padx=14, pady=(0, 8))
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for it in self.catalog.items:
            lp = it.get("local_path", "")
            tag = "missing" if lp and not Path(lp).exists() else ""
            self.tree.insert("", "end", iid=it["id"], values=(it.get("name", ""), it.get("type", ""), it.get("url", ""), lp,
                                                              it.get("description", "")), tags=(tag,))

    def _selected(self) -> List[dict]:
        ids = set(self.tree.selection())
        return [x for x in self.catalog.items if x.get("id") in ids]

    def add(self) -> None:
        self._dialog(None)

    def edit(self) -> None:
        s = self._selected()
        if not s:
            messagebox.showinfo("Surse", "Selecteaza un rand.")
            return
        self._dialog(s[0])

    def delete(self) -> None:
        s = self._selected()
        if s and messagebox.askyesno("Sterge", f"Stergi {len(s)} sursa/surse din catalog?"):
            for it in s:
                self.catalog.delete(it["id"])
            self.refresh()

    def open_web(self) -> None:
        for it in self._selected()[:5]:
            if it.get("url"):
                webbrowser.open(it["url"])

    def open_local(self) -> None:
        s = self._selected()
        if not s:
            return
        it = s[0]
        lp = it.get("local_path", "").strip()
        target = Path(lp) if lp and Path(lp).exists() else self.catalog.resolve_local_file(it.get("url", ""))
        if target and target.exists():
            open_path(target)
        else:
            messagebox.showwarning("Fisier negasit", f"Nu gasesc fisierul local pentru:\n{it.get('name')}\n\nVerifica sincronizarea OneDrive.")

    def open_excel(self) -> None:
        self.catalog.open_excel_file()

    def reload(self) -> None:
        self.catalog.load()
        self.refresh()
        self.app.log(f"[SOURCES] {len(self.catalog.items)} surse reincarcate.", "ok")

    def _dialog(self, existing: Optional[dict]) -> None:
        T, ui = self.T, self.ui
        dlg = tk.Toplevel(self.app)
        dlg.title("Sursa noua" if not existing else f"Editeaza: {existing.get('name')}")
        dlg.geometry("700x330")
        dlg.configure(bg=T["BG2"])
        dlg.transient(self.app)
        dlg.grab_set()
        fields = [("name", "Nume resursa:"), ("type", "Tip (DOCX, Wiki, Portal):"), ("url", "URL SharePoint / Web:"),
                  ("local_path", "Fisier local mapat:"), ("description", "Descriere / note:")]
        vars_ = {}
        for key, lbl in fields:
            row = tk.Frame(dlg, bg=T["BG2"])
            row.pack(fill="x", padx=18, pady=6)
            ui.label(row, lbl, width=24, anchor="w").pack(side="left")
            v = tk.StringVar(value=(existing or {}).get(key, "SharePoint DOCX" if key == "type" else ""))
            vars_[key] = v
            ui.entry(row, v).pack(side="left", fill="x", expand=True, padx=4)
            if key == "local_path":
                ui.btn(row, "…", lambda v=v: v.set(filedialog.askopenfilename() or v.get()), padx=6).pack(side="left")

        def save():
            item = {k: v.get().strip() for k, v in vars_.items()}
            if not item["name"] and not item["url"]:
                messagebox.showerror("Eroare", "Numele sau URL-ul sunt obligatorii.", parent=dlg)
                return
            item["name"] = item["name"] or Path(item["url"].split("?")[0]).name
            item["id"] = (existing or {}).get("id", "")
            self.catalog.add_or_update(item)
            self.refresh()
            dlg.destroy()
        br = tk.Frame(dlg, bg=T["BG2"])
        br.pack(fill="x", padx=18, pady=12)
        ui.btn(br, "Salveaza in catalog", save, primary=True).pack(side="right", padx=4)
        ui.btn(br, "Anuleaza", dlg.destroy).pack(side="right", padx=4)

    def send_selected(self) -> None:
        self._send(self._selected())

    def send_all(self) -> None:
        self._send(list(self.catalog.items))

    def _send(self, items: List[dict]) -> None:
        links = self.app.tab_links
        added_files, recs = 0, []
        for it in items:
            lp, url = it.get("local_path", ""), it.get("url", "")
            resolved = Path(lp) if lp and Path(lp).exists() else (self.catalog.resolve_local_file(url) if url else None)
            if resolved and resolved.exists() and resolved not in links.files:
                links.files.append(resolved)
                added_files += 1
            if url:
                recs.append(LinkRecord(file=it.get("name", "SharePoint Source"), path=str(resolved) if resolved else url,
                                       location="Sources Manager", url=url, source="Sources Manager"))
        n = links.add_records(recs)
        self.app.select_tab("links")
        msg = f"{added_files} documente locale (pentru linkurile interne) + {n} URL-uri SharePoint trimise in Link Checker."
        self.app.log(f"[SOURCES] {msg}", "ok")
        messagebox.showinfo("Surse importate", msg)
