# -*- coding: utf-8 -*-
"""Tab: 🌐 Web Recorder (UCeX)."""
from __future__ import annotations

import datetime
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from ..paths import default_desktop
from ..web.recorder import EXTRACT_KEYS, EXTRACT_LABELS, WebRecorder
from .widgets import make_scrollable, open_path


class WebTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.url = tk.StringVar(value="https://")
        self.browser = tk.StringVar(value="Edge" if sys.platform == "win32" else "Chrome")
        self.headless = tk.BooleanVar(value=False)
        self.out = tk.StringVar(value=str(default_desktop() / "NexusX_WebCapture"))
        self.delay = tk.StringVar(value="0.5")
        self.mode = tk.StringVar(value="full")
        self.mask = tk.BooleanVar(value=True)
        self.opts = {k: tk.BooleanVar(value=(k != "ws")) for k in EXTRACT_KEYS}
        self.recorder: Optional[WebRecorder] = None
        self.last_session: Optional[Path] = None
        self.prog = tk.DoubleVar(value=0)
        self._build(frame)

    def _build(self, frame) -> None:
        ui, T = self.ui, self.T
        top = make_scrollable(frame, T)
        uf = ui.lframe(top, "URL & Browser")
        uf.pack(fill="x", padx=12, pady=(10, 4))
        uf.columnconfigure(1, weight=1)
        ui.label(uf, "URL:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ui.entry(uf, self.url, width=80).grid(row=0, column=1, columnspan=4, sticky="ew", padx=4)
        ui.label(uf, "Browser:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        bf = tk.Frame(uf, bg=T["BG2"])
        bf.grid(row=1, column=1, sticky="w")
        for b in ("Chrome", "Edge", "Firefox"):
            ui.radio(bf, b, self.browser, b).pack(side="left", padx=6)
        ui.chk(bf, "Headless", self.headless).pack(side="left", padx=14)
        ui.chk(bf, "🔒 Mascheaza cookies/tokenuri", self.mask, "Valorile cookie-urilor si tokenurile din storage nu se salveaza in clar").pack(side="left", padx=6)
        ui.label(uf, "Output dir:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ui.entry(uf, self.out, width=64).grid(row=2, column=1, sticky="ew", padx=4)
        ui.btn(uf, "📂", lambda: self.out.set(filedialog.askdirectory() or self.out.get()), padx=8).grid(row=2, column=2, padx=4)

        wm = ui.lframe(top, "Mod Inregistrare")
        wm.pack(fill="x", padx=12, pady=4)
        r = tk.Frame(wm, bg=T["BG2"])
        r.pack(fill="x", padx=8, pady=6)
        for val, lbl in (("full", "● Full Scan (toate extractiile)"), ("custom", "○ Custom Scan (alege ce se extrage)")):
            ui.radio(r, lbl, self.mode, val, command=self._toggle, bold=val == "full").pack(side="left", padx=18)
        self.anchor = tk.Frame(top, bg=T["BG2"])
        self.anchor.pack(fill="x")
        self.custom = ui.lframe(self.anchor, "Optiuni Extractie Custom", fg=T["YELLOW"])
        g = tk.Frame(self.custom, bg=T["BG2"])
        g.pack(fill="x", padx=8, pady=6)
        for i, (key, text, tip) in enumerate(EXTRACT_LABELS):
            ui.chk(g, text, self.opts[key], tip).grid(row=i // 5, column=i % 5, sticky="w", padx=8, pady=2)
        dr = tk.Frame(self.custom, bg=T["BG2"])
        dr.pack(fill="x", padx=8, pady=(0, 6))
        ui.label(dr, "Delay intre citiri (sec):").pack(side="left", padx=8)
        ui.entry(dr, self.delay, width=6).pack(side="left")

        cf = ui.lframe(top, "Controale Inregistrare")
        cf.pack(fill="x", padx=12, pady=4)
        c = tk.Frame(cf, bg=T["BG2"])
        c.pack(fill="x", padx=8, pady=8)
        self.b_start = ui.btn(c, "▶ START Inregistrare", self.start, fg=T["GREEN"])
        self.b_start.pack(side="left", padx=4)
        self.b_pause = ui.btn(c, "⏸ PAUZA", self.pause, fg=T["YELLOW"])
        self.b_pause.pack(side="left", padx=4)
        self.b_stop = ui.btn(c, "⏹ STOP & Salveaza", self.stop, fg=T["RED"])
        self.b_stop.pack(side="left", padx=4)
        self.b_links = ui.btn(c, "🔗 Linkurile capturate → Link Checker", self.links_to_checker, fg=T["ORANGE"])
        self.b_links.pack(side="left", padx=12)
        ui.btn(c, "📦 Instaleaza dependinte", self.install, fg=T["PURPLE"]).pack(side="right", padx=4)
        for b in (self.b_pause, self.b_stop, self.b_links):
            b.configure(state="disabled")
        self.state_var = tk.StringVar(value="⚫ Oprit")
        tk.Label(cf, textvariable=self.state_var, bg=T["BG2"], fg=T["TEXT3"]).pack(anchor="w", padx=12, pady=(0, 6))
        lr = tk.Frame(top, bg=T["BG2"])
        lr.pack(fill="x", padx=12)
        ui.label(lr, "Ultima sesiune:").pack(side="left", padx=8)
        self.last_lbl = ui.label(lr, "—", fg=T["TEXT3"], font=("Segoe UI", 8))
        self.last_lbl.pack(side="left", padx=4)
        self.b_open = ui.btn(lr, "📂 Deschide sesiunea", lambda: open_path(self.last_session) if self.last_session else None, padx=8, pady=3)
        self.b_open.pack(side="left", padx=4)
        self.b_open.configure(state="disabled")
        pf = tk.Frame(top, bg=T["BG3"])
        pf.pack(fill="x", padx=12, pady=(4, 0))
        ui.label(pf, "📊 Progres captare:", fg=T["ACCENT"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=4)
        self.prog_lbl = ui.label(pf, "", fg=T["TEXT3"], font=("Segoe UI", 8, "italic"))
        self.prog_lbl.pack(side="left")
        ttk.Progressbar(pf, variable=self.prog, maximum=100, length=320).pack(side="right", padx=10, pady=4)
        tl = ui.lframe(top, "Timeline Interactiuni")
        tl.pack(fill="both", expand=True, padx=12, pady=4)
        self.timeline = ui.tree(tl, [("time", "TIME", 80, "w"), ("type", "TYPE", 100, "w"), ("element", "ELEMENT", 200, "w"),
                                     ("value", "VALUE", 260, "w"), ("url", "URL", 380, "w")], height=8, selectmode="browse")
        lf = ui.lframe(top, "Log Web Recorder")
        lf.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        fr, self.log_txt = ui.scrolled_text(lf, height=7)
        fr.pack(fill="both", expand=True, padx=4, pady=4)

    def _toggle(self) -> None:
        if self.mode.get() == "custom":
            self.custom.pack(fill="x", padx=12, pady=4)
        else:
            self.custom.pack_forget()

    def log(self, msg: str, tag: str = "info") -> None:
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n", tag)
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")
        self.app.log(f"[WR] {msg}", "error" if tag == "error" else "info")

    def start(self) -> None:
        url = self.url.get().strip()
        if not url or url == "https://":
            messagebox.showerror("Eroare", "Introdu un URL valid!")
            return
        if self.recorder and self.recorder.running:
            return
        opts = {k: True for k in EXTRACT_KEYS} if self.mode.get() == "full" else {k: v.get() for k, v in self.opts.items()}
        try:
            delay = float(self.delay.get().replace(",", "."))
        except ValueError:
            delay = 0.5
        self.timeline.delete(*self.timeline.get_children())
        self.recorder = WebRecorder(url, self.browser.get(), self.headless.get(), Path(self.out.get()), opts, delay, self.mask.get(),
                                    on_log=lambda m, t="info": self.app.call(self.log, m, t),
                                    on_event=lambda ev: self.app.call(self._event, ev),
                                    on_progress=lambda p, l: self.app.call(self._progress, p, l),
                                    on_done=lambda sd: self.app.call(self._done, sd))
        self.recorder.start()
        self.b_start.configure(state="disabled")
        self.b_pause.configure(state="normal")
        self.b_stop.configure(state="normal")
        self.state_var.set("🟢 Inregistrare activa… navigheaza liber in browser, apoi STOP & Salveaza")

    def pause(self) -> None:
        if not self.recorder:
            return
        paused = self.recorder.toggle_pause()
        self.b_pause.configure(text="▶ CONTINUA" if paused else "⏸ PAUZA")
        self.state_var.set("🟡 Pauza…" if paused else "🟢 Inregistrare activa…")

    def stop(self) -> None:
        if self.recorder:
            self.recorder.stop()
        self.b_stop.configure(state="disabled")
        self.b_pause.configure(state="disabled", text="⏸ PAUZA")
        self.state_var.set("💾 Salvare artefacte…")

    def _event(self, ev: dict) -> None:
        self.timeline.insert("", "end", values=(ev.get("time", ""), ev.get("type", ""), ev.get("element", ""),
                                                str(ev.get("value", ""))[:120], str(ev.get("url", ""))[:200]))
        self.timeline.yview_moveto(1)

    def _progress(self, pct: float, label: str) -> None:
        self.prog.set(pct)
        self.prog_lbl.configure(text=label)

    def _done(self, session_dir: Optional[Path]) -> None:
        self.b_start.configure(state="normal")
        self.b_pause.configure(state="disabled")
        self.b_stop.configure(state="disabled")
        self.state_var.set("⚫ Oprit")
        if session_dir:
            self.last_session = session_dir
            self.last_lbl.configure(text=str(session_dir), fg=self.T["GREEN"])
            self.b_open.configure(state="normal")
            self.app.last_outputs = [p for p in session_dir.parent.glob(f"{session_dir.name}.zip")]
            if self.recorder and self.recorder.links:
                self.b_links.configure(state="normal")
            self.app.notify("Web Recorder", f"Sesiune salvata: {session_dir.name}")

    def links_to_checker(self) -> None:
        if not self.recorder or not self.recorder.links:
            return
        urls = list(dict.fromkeys(l.get("href", "") for l in self.recorder.links if l.get("href", "").startswith("http")))
        self.app.tab_links.add_urls(urls, f"Web Recorder: {self.url.get()[:60]}")

    def install(self) -> None:
        self.app.tab_settings.install_deps(["selenium", "webdriver-manager"])
