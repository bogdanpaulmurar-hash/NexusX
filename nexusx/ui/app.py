# -*- coding: utf-8 -*-
"""NexusX main window: header, tabs, status bar, thread-safe dispatcher, tray, e-mail service."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, List, Optional

from .. import APP_LINEAGE, APP_LONG_NAME, APP_NAME, APP_VERSION, AUTHOR, CONTACT
from ..config import ConfigManager
from ..logbus import get_logger, log_queue, tag_for
from ..paths import ICON_PNG, default_report_dir
from .theme import THEMES, apply_styles
from .tray import TrayController, apply_window_icon, set_app_user_model_id, set_dpi_awareness, tray_available
from .widgets import UI, ask_text, open_path


class NexusXApp(tk.Tk):
    def __init__(self, start_minimized: bool = False):
        set_app_user_model_id()
        set_dpi_awareness()
        super().__init__(className=APP_NAME)
        self.cfg = ConfigManager()
        self.logger = get_logger()
        self.theme_name = self.cfg.get("theme", "petrol")
        if self.theme_name not in THEMES:
            self.theme_name = "petrol"
        self.T = THEMES[self.theme_name]
        self.ui = UI(self.T)
        self.title(f"{APP_LONG_NAME}  v{APP_VERSION}")
        self.geometry(self.cfg.get("geometry", "1480x900"))
        self.minsize(1000, 640)
        self.configure(bg=self.T["BG1"])
        self._icon_ref = apply_window_icon(self)
        apply_styles(self, self.T)

        self._calls: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self.status = tk.StringVar(value="Gata. Alege un folder (Ctrl+O) sau adauga documente pentru verificare linkuri.")
        self.progress = tk.DoubleVar(value=0)
        self.report_dir = tk.StringVar(value=str(default_report_dir()))
        self.last_outputs: List[Path] = []
        self.tray: Optional[TrayController] = None
        self._hidden = False

        self._build()
        self._pump()
        self._pump_log()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Unmap>", self._on_unmap)
        self._start_tray()
        if start_minimized and self.tray:
            self.after(300, self.hide_to_tray)
        self.log(f"✅ {APP_NAME} v{APP_VERSION} pornit ({APP_LINEAGE}).", "ok")

    # ── thread-safe helpers ───────────────────────────────────────────────────
    def call(self, fn: Callable, *args, **kw) -> None:
        """Schedule fn on the Tk thread (safe from worker threads)."""
        self._calls.put(lambda: fn(*args, **kw))

    def _pump(self) -> None:
        try:
            for _ in range(200):
                fn = self._calls.get_nowait()
                try:
                    fn()
                except Exception as e:  # noqa: BLE001
                    self.logger.exception(f"UI callback error: {e}")
        except queue.Empty:
            pass
        self.after(40, self._pump)

    def run_bg(self, target: Callable, *args, name: str = "worker") -> threading.Thread:
        def wrapper():
            try:
                target(*args)
            except Exception as e:  # noqa: BLE001
                self.logger.exception(f"Background task '{name}' failed")
                self.call(self.set_status, f"❌ Eroare: {e}")
        t = threading.Thread(target=wrapper, daemon=True, name=name)
        t.start()
        return t

    def ask_on_main(self, fn: Callable[[], object]) -> object:
        """Run a dialog on the Tk thread from a worker and wait for the result."""
        if threading.current_thread() is threading.main_thread():
            return fn()
        box: dict = {}
        ev = threading.Event()

        def run():
            try:
                box["v"] = fn()
            finally:
                ev.set()
        self.call(run)
        ev.wait()
        return box.get("v")

    def ask_password(self, prompt: str) -> Optional[str]:
        return self.ask_on_main(lambda: ask_text(self, APP_NAME, prompt, show="•"))  # type: ignore[return-value]

    # ── status / log / notify ─────────────────────────────────────────────────
    def set_status(self, text: str, progress: Optional[float] = None) -> None:
        self.status.set(text)
        if progress is not None:
            self.progress.set(progress)

    def log(self, msg: str, tag: str = "info") -> None:
        level = {"error": 40, "warn": 30, "debug": 10}.get(tag, 20)
        self.logger.log(level, msg)

    def notify(self, title: str, message: str) -> None:
        if self.tray and self.cfg.get("notify_on_finish", True):
            self.tray.notify(title, message)

    def _pump_log(self) -> None:
        try:
            for _ in range(500):
                msg = log_queue.get_nowait()
                if hasattr(self, "tab_log"):
                    self.tab_log.append(msg, tag_for(msg))
        except queue.Empty:
            pass
        self.after(250, self._pump_log)

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        T = self.T
        hdr = tk.Frame(self, bg=T["BG1"], height=58)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        try:
            self._hdr_img = tk.PhotoImage(file=str(ICON_PNG)).subsample(6, 6) if ICON_PNG.exists() else None
        except Exception:
            self._hdr_img = None
        if self._hdr_img:
            tk.Label(hdr, image=self._hdr_img, bg=T["BG1"]).pack(side="left", padx=(14, 6))
        tk.Label(hdr, text=APP_NAME, font=("Segoe UI", 17, "bold"), bg=T["BG1"], fg=T["ACCENT"]).pack(side="left", pady=10)
        tk.Label(hdr, text=f"  Universal Code & Link eXplorer v{APP_VERSION}  ·  Code Export · Link Map · Link Checker · Web Recorder · Split & Merge · OneNote · Email",
                 font=("Segoe UI", 9), bg=T["BG1"], fg=T["TEXT3"]).pack(side="left", pady=10)
        self.ui.btn(hdr, "ℹ Info", self.show_about).pack(side="right", padx=12)
        self.ui.btn(hdr, "✉ Email rapid", self.quick_email, primary=True).pack(side="right", padx=4)

        sb = tk.Frame(self, bg=T["BG2"], height=28)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        tk.Label(sb, textvariable=self.status, bg=T["BG2"], fg=T["TEXT3"], font=("Segoe UI", 8), anchor="w").pack(
            side="left", padx=10, fill="both", expand=True)
        ttk.Progressbar(sb, variable=self.progress, maximum=100, length=240).pack(side="right", padx=10, pady=6)
        tk.Frame(self, bg=T["SEP"], height=1).pack(fill="x")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6, pady=(4, 6))
        self.nb = nb
        from .tab_code import CodeTab, ManagerTab
        from .tab_linkmap import LinkMapTab
        from .tab_links import LinksTab, SourcesTab
        from .tab_tools import OneNoteTab, SplitMergeTab
        from .tab_web import WebTab
        from .tab_settings import AboutTab, LogTab, SettingsTab

        self.frames = {}
        spec = [("code", " 📦 Code Export ", CodeTab), ("manager", " 🚀 Export Manager ", ManagerTab),
                ("linkmap", " 🕸 Link Map ", LinkMapTab), ("links", " 🔗 Link Checker ", LinksTab),
                ("sources", " 📂 Surse SharePoint ", SourcesTab), ("web", " 🌐 Web Recorder ", WebTab),
                ("splitmerge", " ✂ Split & Merge ", SplitMergeTab), ("onenote", " 📓 OneNote ", OneNoteTab),
                ("settings", " ⚙ Setari ", SettingsTab), ("log", " 📋 Log ", LogTab), ("about", " ℹ Despre ", AboutTab)]
        self.tab_titles = {}
        for key, title, cls in spec:
            frame = tk.Frame(nb, bg=T["BG2"])
            nb.add(frame, text=title)
            self.frames[key] = frame
            self.tab_titles[key] = title
            setattr(self, f"tab_{key}", cls(self, frame))
        vis = self.cfg.get("visible_tabs", {}) or {}
        for key, shown in vis.items():
            if key in self.frames and not shown:
                nb.hide(self.frames[key])

        self.bind("<Control-s>", lambda e: self.tab_code.do_export())
        self.bind("<Control-o>", lambda e: self.tab_code.pick_folder())
        self.bind("<F5>", lambda e: self.tab_code.do_scan())
        self.bind("<Control-l>", lambda e: self.tab_log.clear())
        self.bind("<Control-e>", lambda e: self.quick_email())

    def select_tab(self, key: str) -> None:
        try:
            self.nb.select(self.frames[key])
        except Exception:
            pass

    def set_tab_visible(self, key: str, visible: bool) -> None:
        f = self.frames[key]
        if visible:
            self.nb.add(f, text=self.tab_titles[key])
        else:
            self.nb.hide(f)
        vis = self.cfg.get("visible_tabs", {}) or {}
        vis[key] = visible
        self.cfg.set("visible_tabs", vis)

    # ── e-mail ───────────────────────────────────────────────────────────────
    def send_mail(self, subject: str, html_body: str, attachments: List[Path], label: str = "Email") -> None:
        """Deliver in the background with the method configured in Settings → Email."""
        from .. import mailer
        cfg = self.cfg.email()
        self.set_status("✉ Pregatire email…")
        self.log(f"[EMAIL] {subject} — {len(attachments)} atasamente, metoda: {cfg.get('method')}")

        def work():
            ok, msg = mailer.send_email(subject, html_body, attachments, cfg, self.ensure_report_dir(),
                                        ask_password=self.ask_password)
            self.call(self.log, ("✅ " if ok else "❌ ") + msg, "ok" if ok else "error")
            self.call(self.set_status, msg)
            if ok:
                self.call(self.notify, label, msg)
            else:
                self.call(messagebox.showerror, label, msg)
        self.run_bg(work, name="email")

    def quick_email(self) -> None:
        """Header/tray button: e-mail whatever is relevant for the active tab."""
        try:
            current = self.nb.index(self.nb.select())
            key = list(self.frames)[current]
        except Exception:
            key = "links"
        if key in ("links", "sources") or (key not in ("code", "manager", "linkmap") and self.tab_links.records):
            self.tab_links.compose_email()
        elif key == "linkmap":
            self.tab_linkmap.email()
        else:
            self.tab_code.email_last()

    # ── tray / window ────────────────────────────────────────────────────────
    def _start_tray(self) -> None:
        if not self.cfg.get("tray_enabled", True):
            return
        if not tray_available():
            self.log("ℹ Tray dezactivat: instaleaza 'pystray' si 'Pillow' (Setari → Dependinte).", "debug")
            return
        actions = {
            "scan_export": lambda: (self.show_window(), self.tab_code.do_scan(then_export=True)),
            "run_manager": lambda: self.tab_manager.run(),
            "check_links": lambda: (self.show_window(), self.select_tab("links"), self.tab_links.scan_http()),
            "linkmap": lambda: (self.show_window(), self.select_tab("linkmap"), self.tab_linkmap.run()),
            "email": self.quick_email,
            "open_reports": lambda: open_path(self.ensure_report_dir()),
        }
        self.tray = TrayController(self, actions, self.show_window, self.hide_to_tray, self.exit_app, self.call)
        if not self.tray.start():
            self.tray = None

    def ensure_report_dir(self) -> Path:
        p = Path(self.report_dir.get())
        p.mkdir(parents=True, exist_ok=True)
        return p

    def show_window(self) -> None:
        self.deiconify()
        self.state("normal")
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(300, lambda: self.attributes("-topmost", False))
        except Exception:
            pass
        self.focus_force()
        self._hidden = False

    def hide_to_tray(self) -> None:
        if self.tray:
            self.withdraw()
            self._hidden = True
            self.tray.notify(APP_NAME, "Ruleaza in tray. Click pe icon pentru a reveni.")
        else:
            self.iconify()

    def _on_unmap(self, event) -> None:
        if event.widget is self and self.tray and self.cfg.get("minimize_to_tray", False) and self.state() == "iconic":
            self.after(50, self.hide_to_tray)

    def on_close(self) -> None:
        if self.tray and self.cfg.get("close_to_tray", False):
            self.hide_to_tray()
            return
        self.exit_app()

    def exit_app(self) -> None:
        busy = self.tab_web.recorder is not None and self.tab_web.recorder.running
        if busy:
            self.tab_web.stop()
        try:
            if self.state() == "normal":
                self.cfg.set("geometry", self.geometry())
        except Exception:
            pass
        if self.tray:
            self.tray.stop()
        self.destroy()

    def show_about(self) -> None:
        messagebox.showinfo(f"Despre {APP_NAME}", (
            f"{APP_LONG_NAME} v{APP_VERSION}\nSuccesorul combinat al {APP_LINEAGE}\n\n"
            f"Autor: {AUTHOR}\nSuport: Teams sau {CONTACT}\n\n"
            "• Export cod complet (txt/md/html/json, split, ZIP, rezumat folder, redactare secrete)\n"
            "• Link Map: legaturile dintre tool-uri, URL-uri, cai, DB, SSO, automatizari\n"
            "• Link Checker: DOCX/PDF/XLSX/PPTX/HTML/MD, cross-references Word, crawl pagina,\n"
            "  HTTP paralel + browser headless/SSO, export 6 formate\n"
            "• Web Recorder: captura completa sesiune + script de replay\n"
            "• Email cu un click (Outlook / SMTP / .eml), icon in taskbar + tray"))
