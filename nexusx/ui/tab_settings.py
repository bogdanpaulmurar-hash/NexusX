# -*- coding: utf-8 -*-
"""Tabs: ⚙ Settings, 📋 Log, ℹ About."""
from __future__ import annotations

import datetime
import importlib
import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List

from .. import APP_LINEAGE, APP_NAME, APP_VERSION, AUTHOR, CONTACT
from ..codex.constants import EXT_GROUPS
from ..paths import CONFIG_FILE, LOG_FILE
from .theme import THEME_LABELS
from .tray import tray_available
from .widgets import make_scrollable, open_path

DEPENDENCIES = [  # (import name, pip package, purpose)
    ("docx", "python-docx", "Rapoarte Word"),
    ("openpyxl", "openpyxl", "Rapoarte Excel + catalog surse"),
    ("fitz", "PyMuPDF", "Linkuri din PDF"),
    ("playwright", "playwright", "Verificare in browser / SSO"),
    ("selenium", "selenium", "Web Recorder"),
    ("webdriver_manager", "webdriver-manager", "Web Recorder (drivere)"),
    ("PIL", "Pillow", "Icon tray + info imagini"),
    ("pystray", "pystray", "Icon in system tray"),
    ("truststore", "truststore", "Certificate corporative (SSL)"),
    ("keyring", "keyring", "Parola SMTP in Windows Credential Manager"),
    ("win32com", "pywin32", "Email prin Outlook"),
]


class SettingsTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self._build(frame)

    def _build(self, frame) -> None:
        ui, T, cfg = self.ui, self.T, self.app.cfg
        top = make_scrollable(frame, T)
        tk.Label(top, text=f"⚙️ Setari — {APP_NAME} v{APP_VERSION}", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=16, pady=(16, 4))

        af = ui.lframe(top, "Aspect & Tema")
        af.pack(fill="x", padx=16, pady=6)
        r = tk.Frame(af, bg=T["BG2"])
        r.pack(fill="x", padx=8, pady=8)
        for name, lbl in THEME_LABELS.items():
            sel = self.app.theme_name == name
            ui.btn(r, lbl, lambda n=name: self.apply_theme(n), primary=sel).pack(side="left", padx=6)

        vf = ui.lframe(top, "Taburi vizibile")
        vf.pack(fill="x", padx=16, pady=6)
        vr = tk.Frame(vf, bg=T["BG2"])
        vr.pack(fill="x", padx=8, pady=8)
        vis = cfg.get("visible_tabs", {}) or {}
        for key in ("manager", "linkmap", "links", "sources", "web"):
            v = tk.BooleanVar(value=vis.get(key, True))
            ui.chk(vr, self.app.tab_titles[key].strip(), v, command=lambda k=key, var=v: self.app.set_tab_visible(k, var.get())).pack(side="left", padx=8)

        ef = ui.lframe(top, "Filtru extensii & export cod")
        ef.pack(fill="x", padx=16, pady=6)
        er = tk.Frame(ef, bg=T["BG2"])
        er.pack(fill="x", padx=8, pady=8)
        ui.btn(er, "🔧 Deschide Filtru Extensii", self.open_filter_dialog, fg=T["PURPLE"]).pack(side="left", padx=4)
        self.redact = tk.BooleanVar(value=cfg.get("redact_secrets", True))
        self.gitignore = tk.BooleanVar(value=cfg.get("respect_gitignore", False))
        ui.chk(er, "Redactare secrete implicit", self.redact, command=lambda: (cfg.set("redact_secrets", self.redact.get()),
                                                                            self.app.tab_code.redact.set(self.redact.get()))).pack(side="left", padx=12)
        ui.chk(er, "Respecta .gitignore implicit", self.gitignore, command=lambda: (cfg.set("respect_gitignore", self.gitignore.get()),
                                                                                 self.app.tab_code.gitignore.set(self.gitignore.get()))).pack(side="left", padx=6)

        mf = ui.lframe(top, "✉ Email (buton cu un click)", fg=T["YELLOW"])
        mf.pack(fill="x", padx=16, pady=6)
        e = cfg.email()
        self.mail = {k: tk.StringVar(value=str(e.get(k, ""))) for k in
                     ("to", "cc", "subject_links", "subject_code", "signature", "smtp_host", "smtp_port", "smtp_user",
                      "smtp_from", "zip_attachments_over_mb")}
        self.method = tk.StringVar(value=e.get("method", "outlook"))
        self.direct = tk.BooleanVar(value=bool(e.get("outlook_send_direct")))
        self.tls = tk.BooleanVar(value=bool(e.get("smtp_tls", True)))
        self.lang = tk.StringVar(value=cfg.get("language_email", "de"))
        m0 = tk.Frame(mf, bg=T["BG2"])
        m0.pack(fill="x", padx=8, pady=(8, 2))
        ui.label(m0, "Metoda:").pack(side="left", padx=4)
        for val, lbl in (("outlook", "Outlook (pywin32)"), ("smtp", "SMTP"), ("eml", "Fisier .eml (orice client)")):
            ui.radio(m0, lbl, self.method, val).pack(side="left", padx=6)
        ui.chk(m0, "Outlook: trimite direct (fara previzualizare)", self.direct,
               "Debifat = mailul se deschide in Outlook pentru verificare (ca in ULaE).").pack(side="left", padx=12)
        ui.label(m0, "Limba template:").pack(side="left", padx=(12, 4))
        ttk.Combobox(m0, textvariable=self.lang, values=["de", "ro", "en"], state="readonly", width=4).pack(side="left")
        grid = tk.Frame(mf, bg=T["BG2"])
        grid.pack(fill="x", padx=8, pady=4)
        rows = [("Catre (To):", "to"), ("CC:", "cc"), ("Subiect linkuri:", "subject_links"), ("Subiect cod:", "subject_code"),
                ("Semnatura:", "signature"), ("SMTP host:", "smtp_host"), ("SMTP port:", "smtp_port"), ("SMTP user:", "smtp_user"),
                ("Expeditor (From):", "smtp_from"), ("ZIP peste (MB):", "zip_attachments_over_mb")]
        for i, (lbl, key) in enumerate(rows):
            ui.label(grid, lbl).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=6, pady=3)
            ui.entry(grid, self.mail[key], width=44).grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="ew", padx=4, pady=3)
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        m2 = tk.Frame(mf, bg=T["BG2"])
        m2.pack(fill="x", padx=8, pady=(2, 8))
        ui.chk(m2, "SMTP STARTTLS", self.tls).pack(side="left", padx=4)
        ui.btn(m2, "💾 Salveaza setari email", self.save_email, primary=True).pack(side="left", padx=10)
        ui.btn(m2, "✉ Trimite email de test", self.test_email).pack(side="left", padx=4)
        ui.label(m2, "Parola SMTP nu se salveaza in config (Windows Credential Manager prin 'keyring', daca e instalat).",
                 fg=T["TEXT3"], font=("Segoe UI", 8)).pack(side="left", padx=10)

        tf = ui.lframe(top, "Taskbar & System tray")
        tf.pack(fill="x", padx=16, pady=6)
        tr = tk.Frame(tf, bg=T["BG2"])
        tr.pack(fill="x", padx=8, pady=8)
        self.tray_vars = {}
        for key, lbl in (("tray_enabled", "Icon in tray"), ("close_to_tray", "X inchide in tray"),
                         ("minimize_to_tray", "Minimizare in tray"), ("notify_on_finish", "Notificari la final de task")):
            v = tk.BooleanVar(value=bool(cfg.get(key)))
            self.tray_vars[key] = v
            ui.chk(tr, lbl, v, command=lambda k=key, var=v: cfg.set(k, var.get())).pack(side="left", padx=8)
        tray_lbl = ui.label(tf, "", fg=T["TEXT3"], font=("Segoe UI", 8, "italic"))
        tray_lbl.pack(anchor="w", padx=12, pady=(0, 6))
        self.app.after(1200, lambda: tray_lbl.configure(
            text="Tray activ ✅ (click dreapta pe icon pentru actiuni rapide)" if self.app.tray else
            ("Tray indisponibil: instaleaza pystray + Pillow" if not tray_available() else "Tray dezactivat din setari (necesita repornire)")))

        df = ui.lframe(top, "Dependinte Python")
        df.pack(fill="x", padx=16, pady=6)
        dr = tk.Frame(df, bg=T["BG2"])
        dr.pack(fill="x", padx=8, pady=8)
        ui.btn(dr, "📦 Instaleaza toate dependintele", lambda: self.install_deps([d[1] for d in DEPENDENCIES], playwright=True),
               fg=T["GREEN"]).pack(side="left", padx=4)
        ui.btn(dr, "🔍 Verifica dependinte", self.check_deps, fg=T["TEAL"]).pack(side="left", padx=8)
        fr, self.dep_log = ui.scrolled_text(df, height=7)
        fr.pack(fill="x", padx=8, pady=(0, 8))

        cf = ui.lframe(top, "Controale aplicatie")
        cf.pack(fill="x", padx=16, pady=6)
        cr = tk.Frame(cf, bg=T["BG2"])
        cr.pack(fill="x", padx=8, pady=8)
        ui.btn(cr, "💾 Salveaza & Reporneste", self.restart, fg=T["ACCENT"]).pack(side="left", padx=4)
        ui.btn(cr, "🔄 Resetare config", self.reset, fg=T["YELLOW"]).pack(side="left", padx=6)
        ui.btn(cr, "📂 Folder config/log", lambda: open_path(LOG_FILE.parent), fg=T["TEAL"]).pack(side="left", padx=6)
        ui.btn(cr, "🖥 Creeaza scurtatura Desktop", self.create_shortcut).pack(side="left", padx=6)
        ui.btn(cr, "📖 Instructiuni", self.instructions, fg=T["PINK"]).pack(side="left", padx=6)
        ui.btn(cr, "❌ Exit", self.app.exit_app, fg=T["RED"]).pack(side="left", padx=6)
        ui.label(top, f"Config: {CONFIG_FILE}    Log: {LOG_FILE}", fg=T["TEXT3"], font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(4, 16))
        self.app.after(1500, self.check_deps)

    # ── theme / config ──
    def apply_theme(self, name: str) -> None:
        self.app.cfg.set("theme", name)
        if messagebox.askyesno("Tema", f"Tema '{THEME_LABELS[name]}' salvata.\nRepornesti aplicatia acum?"):
            self.restart(save=False)

    def restart(self, save: bool = True) -> None:
        if save:
            self.app.cfg.save()
        if self.app.tray:
            self.app.tray.stop()
        self.app.destroy()
        os.execl(sys.executable, sys.executable, *sys.argv)

    def reset(self) -> None:
        if messagebox.askyesno("Resetare", "Resetezi configuratia la valorile implicite? (perechile Export Manager raman in fisierele exportate)"):
            self.app.cfg.reset()
            messagebox.showinfo("Resetare", "Config resetat. Reporneste aplicatia.")

    # ── email ──
    def save_email(self) -> None:
        vals = {k: v.get().strip() for k, v in self.mail.items()}
        try:
            vals["smtp_port"] = int(vals.get("smtp_port") or 587)
            vals["zip_attachments_over_mb"] = float(vals.get("zip_attachments_over_mb") or 15)
        except ValueError:
            messagebox.showerror("Email", "Port / prag ZIP trebuie sa fie numere.")
            return
        self.app.cfg.set_email(method=self.method.get(), outlook_send_direct=self.direct.get(), smtp_tls=self.tls.get(), **vals)
        self.app.cfg.set("language_email", self.lang.get())
        self.app.log("✅ Setari email salvate.", "ok")
        self.app.set_status("Setari email salvate.")

    def test_email(self) -> None:
        self.save_email()
        from .. import mailer
        body = mailer._wrap(f"<p>Test {APP_NAME} v{APP_VERSION} — {datetime.datetime.now():%Y-%m-%d %H:%M}</p>")
        self.app.send_mail(f"{APP_NAME} — email de test", body, [], "Email test")

    # ── extension filter (UCeX) ──
    def open_filter_dialog(self) -> None:
        T, ui = self.T, self.ui
        dlg = tk.Toplevel(self.app)
        dlg.title("Filtru extensii")
        dlg.configure(bg=T["BG1"])
        dlg.geometry("1000x600")
        dlg.transient(self.app)
        holder = tk.Frame(dlg, bg=T["BG2"])
        holder.pack(fill="both", expand=True)
        inner = make_scrollable(holder, T)
        tk.Label(inner, text="Selecteaza extensiile incluse la export (se aplica si in Export Manager):", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))
        grid = tk.Frame(inner, bg=T["BG2"])
        grid.pack(fill="x", padx=4, pady=4)
        ev = self.app.ext_vars
        for i, (grp, exts) in enumerate(EXT_GROUPS.items()):
            f = tk.LabelFrame(grid, text=f" {grp} ", bg=T["BG2"], fg=T["PURPLE"], font=("Segoe UI", 9, "bold"),
                              relief="flat", highlightbackground=T["SEP"], highlightthickness=1)
            f.grid(row=i // 7, column=i % 7, padx=5, pady=5, sticky="n")
            for ext in exts:
                ui.chk(f, ext, ev.setdefault(ext, tk.BooleanVar(value=True))).pack(anchor="w", padx=6)
            b = tk.Frame(f, bg=T["BG2"])
            b.pack(fill="x", padx=4, pady=2)
            ui.btn(b, "✅", lambda e=exts: self._bulk(e, True), bold=False, padx=6, pady=1).pack(side="left", padx=2)
            ui.btn(b, "❌", lambda e=exts: self._bulk(e, False), bold=False, padx=6, pady=1).pack(side="left")
        gb = tk.Frame(dlg, bg=T["BG1"])
        gb.pack(fill="x", padx=14, pady=6)
        ui.btn(gb, "✅ Toate", lambda: self._bulk(list(ev), True)).pack(side="left", padx=4)
        ui.btn(gb, "❌ Niciuna", lambda: self._bulk(list(ev), False)).pack(side="left", padx=4)
        ui.btn(gb, "💾 Salveaza & Inchide", lambda: (self._persist_exts(), dlg.destroy()), primary=True).pack(side="right", padx=4)

    def _bulk(self, exts, val: bool) -> None:
        for e in exts:
            if e in self.app.ext_vars:
                self.app.ext_vars[e].set(val)

    def _persist_exts(self) -> None:
        disabled = [e for e, v in self.app.ext_vars.items() if not v.get()]
        self.app.cfg.set("disabled_exts", disabled)
        self.app.tab_code.update_estimate()
        self.app.log(f"Filtru extensii salvat ({len(disabled)} dezactivate).", "ok")

    # ── deps ──
    def dep_log_msg(self, msg: str, tag: str = "info") -> None:
        self.dep_log.configure(state="normal")
        self.dep_log.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n", tag)
        self.dep_log.see("end")
        self.dep_log.configure(state="disabled")

    def check_deps(self) -> None:
        def work():
            missing = []
            for mod, pkg, purpose in DEPENDENCIES:
                try:
                    importlib.import_module(mod)
                    self.app.call(self.dep_log_msg, f"✅ {pkg:<18} — {purpose}", "ok")
                except Exception:
                    missing.append(pkg)
                    self.app.call(self.dep_log_msg, f"⚠️ {pkg:<18} lipseste — {purpose}", "warn")
            self.app.call(self.dep_log_msg, "Toate dependintele sunt instalate." if not missing else
                          f"Lipsesc: {', '.join(missing)} → 'Instaleaza toate dependintele'", "ok" if not missing else "warn")
        self.app.run_bg(work, name="deps")

    def install_deps(self, packages: List[str], playwright: bool = False) -> None:
        self.app.select_tab("settings")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        def work():
            self.app.call(self.dep_log_msg, f"Instalare: {' '.join(packages)} …")
            pkgs = [p for p in packages if not (p == "pywin32" and sys.platform != "win32")]
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", *pkgs], capture_output=True, text=True,
                               timeout=900, creationflags=flags)
            self.app.call(self.dep_log_msg, "✅ pip install OK" if r.returncode == 0 else f"❌ pip: {r.stderr[-600:]}",
                          "ok" if r.returncode == 0 else "error")
            if playwright:
                r2 = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], capture_output=True, text=True,
                                    timeout=900, creationflags=flags)
                self.app.call(self.dep_log_msg, "✅ Chromium pentru Playwright instalat" if r2.returncode == 0 else
                              f"❌ playwright install: {r2.stderr[-400:]}", "ok" if r2.returncode == 0 else "error")
            self.app.call(self.check_deps)
        self.app.run_bg(work, name="pip")

    def create_shortcut(self) -> None:
        if sys.platform != "win32":
            messagebox.showinfo("Scurtatura", "Disponibil doar pe Windows.")
            return
        root = Path(__file__).resolve().parents[2]
        target = Path(sys.executable).with_name("pythonw.exe")
        if not target.exists():
            target = Path(sys.executable)
        ico = root / "assets" / "nexusx.ico"
        lnk = Path(os.path.expandvars(r"%USERPROFILE%")) / "Desktop" / f"{APP_NAME}.lnk"
        ps = (f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut("{lnk}");'
              f'$s.TargetPath="{target}";$s.Arguments="-m nexusx";$s.WorkingDirectory="{root}";'
              f'$s.IconLocation="{ico}";$s.Description="{APP_NAME} — Universal Code & Link eXplorer";$s.Save()')
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            messagebox.showinfo("Scurtatura", f"Creata: {lnk}\nClick dreapta pe ea → 'Pin to taskbar' pentru icon permanent in taskbar.")
        else:
            messagebox.showerror("Scurtatura", r.stderr[-400:])

    def instructions(self) -> None:
        T = self.T
        dlg = tk.Toplevel(self.app)
        dlg.title(f"📖 Instructiuni {APP_NAME}")
        dlg.configure(bg=T["BG1"])
        dlg.geometry("900x680")
        fr, txt = self.ui.scrolled_text(dlg, height=40)
        fr.pack(fill="both", expand=True, padx=8, pady=8)
        txt.configure(state="normal", wrap="word")
        readme = Path(__file__).resolve().parents[2] / "README.md"
        txt.insert("1.0", readme.read_text(encoding="utf-8") if readme.exists() else "README.md lipseste.")
        txt.configure(state="disabled")


class LogTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.entries: List[tuple] = []
        ui, T = self.ui, self.T
        c = tk.Frame(frame, bg=T["BG2"])
        c.pack(fill="x", padx=12, pady=6)
        ui.btn(c, "🗑️ Sterge Log (Ctrl+L)", self.clear, fg=T["RED"]).pack(side="left")
        ui.btn(c, "📂 Deschide logfile", lambda: open_path(LOG_FILE), fg=T["TEAL"]).pack(side="left", padx=6)
        ui.btn(c, "💾 Export Log", self.export, fg=T["PURPLE"]).pack(side="left", padx=6)
        ui.label(c, "  Filtru:").pack(side="left", padx=4)
        self.flt = tk.StringVar()
        e = ui.entry(c, self.flt, width=30)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda ev: self.refilter())
        ui.label(c, " Nivel:").pack(side="left", padx=4)
        self.level = tk.StringVar(value="ALL")
        cb = ttk.Combobox(c, textvariable=self.level, values=["ALL", "INFO", "OK", "WARN", "ERROR", "DEBUG"], state="readonly", width=8)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda ev: self.refilter())
        self.count = ui.label(c, "0 intrari", fg=T["TEXT3"], font=("Segoe UI", 8))
        self.count.pack(side="left", padx=12)
        fr, self.txt = ui.scrolled_text(frame, height=36)
        fr.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    def _show(self, msg: str, tag: str) -> bool:
        q = self.flt.get().lower()
        if q and q not in msg.lower():
            return False
        lv = self.level.get()
        return lv == "ALL" or tag == {"INFO": "info", "OK": "ok", "WARN": "warn", "ERROR": "error", "DEBUG": "debug"}[lv]

    def append(self, msg: str, tag: str) -> None:
        self.entries.append((msg, tag))
        if len(self.entries) > 20000:
            self.entries = self.entries[-15000:]
        if self._show(msg, tag):
            self.txt.configure(state="normal")
            self.txt.insert("end", msg + "\n", tag)
            self.txt.see("end")
            self.txt.configure(state="disabled")
        self.count.configure(text=f"{len(self.entries)} intrari")

    def refilter(self) -> None:
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        for m, t in self.entries:
            if self._show(m, t):
                self.txt.insert("end", m + "\n", t)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def clear(self) -> None:
        self.entries.clear()
        self.refilter()
        self.count.configure(text="0 intrari")

    def export(self) -> None:
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")],
                                         initialfile=f"NexusX_log_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt")
        if p:
            Path(p).write_text("\n".join(f"[{t.upper()}] {m}" for m, t in self.entries), encoding="utf-8")


class AboutTab:
    def __init__(self, app, frame):
        T = app.T
        c = tk.Frame(frame, bg=T["BG2"])
        c.pack(fill="both", expand=True, padx=25, pady=20)
        card = tk.Frame(c, bg=T["BG3"], padx=20, pady=16)
        card.pack(fill="x", pady=(0, 14))
        if getattr(app, "_icon_ref", None):
            try:
                self._img = app._icon_ref.subsample(3, 3)
                tk.Label(card, image=self._img, bg=T["BG3"]).pack(side="left", padx=(0, 16))
            except Exception:
                pass
        box = tk.Frame(card, bg=T["BG3"])
        box.pack(side="left", fill="x")
        tk.Label(box, text=f"{APP_NAME} v{APP_VERSION} — Universal Code & Link eXplorer", font=("Segoe UI", 15, "bold"),
                 bg=T["BG3"], fg=T["ACCENT"]).pack(anchor="w")
        tk.Label(box, text=f"Succesorul unificat al {APP_LINEAGE} · Siemens AG", bg=T["BG3"], fg=T["TEXT2"]).pack(anchor="w")
        desc = tk.Frame(c, bg=T["BG3"], padx=20, pady=16)
        desc.pack(fill="x", pady=(0, 14))
        texts = [
            ("🇷🇴 Descriere", "NexusX exporta tot ce se poate dintr-un cod (si din pagini web) ca sa se poata stabili legaturile dintre "
                              "tool-urile create prin vibe coding, aplicatii, browsere si logari securizate din companie (Link Map), si verifica "
                              "daca linkurile dintr-un document, dintr-o pagina sau dintre sectiunile unui Word mai sunt actuale si functionale."),
            ("🇩🇪 Beschreibung", "NexusX exportiert Quellcode und Webseiten vollständig, kartiert die Verbindungen zwischen Tools, Browsern und "
                                 "Firmensystemen und prüft Hyperlinks, Querverweise und Lesezeichen in Office-Dokumenten — mit Berichten in 6 Formaten "
                                 "und Outlook-E-Mail auf Knopfdruck."),
            ("🇬🇧 Description", "NexusX exports code and web sessions, maps how your tools connect to each other and to company systems, and audits "
                                "hyperlinks, cross-references and bookmarks in documents and pages — one-click e-mail reports included."),
        ]
        for h, t in texts:
            tk.Label(desc, text=h, bg=T["BG3"], fg=T["TEXT1"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
            tk.Label(desc, text=t, bg=T["BG3"], fg=T["TEXT2"], wraplength=1100, justify="left").pack(anchor="w", pady=(2, 10))
        meta = tk.Frame(c, bg=T["BG3"], padx=20, pady=16)
        meta.pack(fill="x")
        for k, v in (("👤 Autor:", AUTHOR), ("✉ Suport:", f"Teams sau {CONTACT}"),
                     ("🐙 GitHub:", "https://github.com/bogdanpaulmurar-hash/UCeX-_-ULeX")):
            row = tk.Frame(meta, bg=T["BG3"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=k, width=12, anchor="w", bg=T["BG3"], fg=T["ACCENT"], font=("Segoe UI", 9, "bold")).pack(side="left")
            lbl = tk.Label(row, text=v, bg=T["BG3"], fg=T["TEXT1"], cursor="hand2" if v.startswith("http") else "")
            lbl.pack(side="left")
            if v.startswith("http"):
                lbl.bind("<Button-1>", lambda e, u=v: webbrowser.open(u))
