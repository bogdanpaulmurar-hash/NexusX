# -*- coding: utf-8 -*-
"""Tabs: 📦 Code Export (UCeX Scan & Export) and 🚀 Export Manager."""
from __future__ import annotations

import datetime
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

from .. import mailer
from ..codex import exporter, linkmap
from ..codex.constants import ALL_EXTS, DEFAULT_EXCLUDED, matches_exts
from ..codex.scanner import MB, ScanOptions, enrich, scan_folder
from ..codex.summary import SUMMARY_DEFAULTS, SUMMARY_OPTIONS, build_summary
from ..paths import default_desktop
from .widgets import make_scrollable, open_path, reveal

PRESET_NONE = "— Selecteaza Preconfiguratie —"


def build_split_row(app, parent) -> None:
    """Shared split controls (UCeX _build_split_ui_inline); all rows share the same variables."""
    ui, T = app.ui, app.T
    cb = ui.chk(parent, "Split export", app.split_enabled, fg=T["YELLOW"], command=lambda: _split_toggle(app),
                tip='Imparte exportul in parti. Fiecare parte se termina cu\n"END PART N/M — CONTINUA CU: fisier_part2.txt"')
    cb.pack(side="left", padx=8)
    widgets = []
    for val, lbl in (("none", "Complet"), ("50mb", "50 MB"), ("99mb", "99 MB"), ("custom", "Custom:")):
        rb = ui.radio(parent, lbl, app.split_mode, val)
        rb.pack(side="left", padx=4)
        widgets.append(rb)
    ce = ui.entry(parent, app.split_custom, width=5)
    ce.pack(side="left", padx=2)
    widgets.append(ce)
    ui.label(parent, "MB", fg=T["TEXT3"]).pack(side="left")
    app.split_widgets.extend(widgets)
    _split_toggle(app)


def _split_toggle(app) -> None:
    state = "normal" if app.split_enabled.get() else "disabled"
    for w in app.split_widgets:
        try:
            w.configure(state=state)
        except Exception:
            pass


def current_split_bytes(app) -> Optional[int]:
    if not app.split_enabled.get():
        return None
    return exporter.split_bytes_for(app.split_mode.get(), app.split_custom.get())


class CodeTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        cfg = app.cfg
        # shared state on the app (used by Manager / Web / Settings)
        app.split_enabled = tk.BooleanVar(value=False)
        app.split_mode = tk.StringVar(value="50mb")
        app.split_custom = tk.StringVar(value="50")
        app.split_widgets = []
        disabled = set(cfg.get("disabled_exts", []) or [])
        app.ext_vars = {ext: tk.BooleanVar(value=ext not in disabled) for ext in ALL_EXTS}
        app.export_pairs = cfg.get_export_pairs()

        self.folder = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(default_desktop()))
        self.out_name = tk.StringVar(value="NexusX_Export")
        self.out_fmt = tk.StringVar(value=".txt")
        self.scan_mode = tk.StringVar(value="full")
        self.recursive = tk.BooleanVar(value=True)
        self.skip_hidden = tk.BooleanVar(value=True)
        self.max_mb = tk.StringVar(value="5")
        self.excl = tk.StringVar(value=DEFAULT_EXCLUDED)
        self.add_header = tk.BooleanVar(value=True)
        self.add_toc = tk.BooleanVar(value=True)
        self.add_stats = tk.BooleanVar(value=True)
        self.add_md5 = tk.BooleanVar(value=True)
        self.add_lnum = tk.BooleanVar(value=False)
        self.compress_ws = tk.BooleanVar(value=False)
        self.inc_binary = tk.BooleanVar(value=False)
        self.redact = tk.BooleanVar(value=bool(cfg.get("redact_secrets", True)))
        self.gitignore = tk.BooleanVar(value=bool(cfg.get("respect_gitignore", False)))
        self.add_linkmap = tk.BooleanVar(value=False)
        self.preset = tk.StringVar(value=PRESET_NONE)
        self.files_all: List[Path] = []
        self.last_export: Optional[Path] = None
        self.last_parts: List[Path] = []
        self.last_stats: Dict[str, object] = {}
        self.busy = False
        self._build(frame)

    # ── layout ────────────────────────────────────────────────────────────────
    def _build(self, frame) -> None:
        ui, T = self.ui, self.T
        top = make_scrollable(frame, T)
        self.top = top

        ff = ui.lframe(top, "Folder Sursa")
        ff.pack(fill="x", padx=12, pady=(10, 4))
        ff.columnconfigure(1, weight=1)
        ui.label(ff, "Folder:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        e = ui.entry(ff, self.folder, width=70)
        e.grid(row=0, column=1, sticky="ew", padx=4, pady=6)
        ui.tooltip(e, "Folderul radacina de scanat (Ctrl+O). Poti lipi si o cale din Explorer.")
        ui.btn(ff, "📂 Browse", self.pick_folder, fg=T["ACCENT"]).grid(row=0, column=2, padx=6)

        pf = ui.lframe(top, "⚡ Incarca Preconfiguratie din Export Manager", fg=T["PURPLE"])
        pf.pack(fill="x", padx=12, pady=(0, 4))
        row = tk.Frame(pf, bg=T["BG2"])
        row.pack(fill="x", padx=8, pady=6)
        ui.label(row, "Proiect:").pack(side="left", padx=(0, 6))
        from tkinter import ttk
        self.preset_cb = ttk.Combobox(row, textvariable=self.preset, state="readonly", width=38)
        self.preset_cb.pack(side="left", padx=4)
        self.preset_cb.bind("<<ComboboxSelected>>", self._on_preset)
        ui.btn(row, "📥 Incarca in Scan", self.load_preset, fg=T["PURPLE"]).pack(side="left", padx=8)
        ui.btn(row, "🔄 Refresh", self.refresh_presets, fg=T["TEAL"]).pack(side="left", padx=4)
        self.preset_info = ui.label(row, "", fg=T["TEXT3"], font=("Segoe UI", 8, "italic"))
        self.preset_info.pack(side="left", padx=8)
        self.refresh_presets()

        mf = ui.lframe(top, "Mod Scanare")
        mf.pack(fill="x", padx=12, pady=4)
        mrow = tk.Frame(mf, bg=T["BG2"])
        mrow.pack(fill="x", padx=8, pady=6)
        for val, lbl, tip in (("full", "● Full Scan (recursiv, fara ascunse, max 5 MB, excluderi implicite)", "Setarile implicite UCeX"),
                              ("custom", "○ Custom Scan (optiuni avansate)", "Afiseaza panoul cu optiuni")):
            rb = ui.radio(mrow, lbl, self.scan_mode, val, command=self._toggle_custom, bold=val == "full")
            rb.pack(side="left", padx=14)
            ui.tooltip(rb, tip)
        self.custom_anchor = tk.Frame(top, bg=T["BG2"])
        self.custom_anchor.pack(fill="x")
        cp = ui.lframe(self.custom_anchor, "Optiuni Custom Scan", fg=T["YELLOW"])
        self.custom_panel = cp
        r0 = tk.Frame(cp, bg=T["BG2"])
        r0.pack(fill="x", padx=8, pady=4)
        for text, var, tip in (("Recursiv", self.recursive, "Scaneaza si subdirectoarele"),
                               ("Skip hidden", self.skip_hidden, "Sare fisierele/folderele ascunse"),
                               ("Respecta .gitignore", self.gitignore, "Ignora ce exclude .gitignore din radacina")):
            ui.chk(r0, text, var, tip).pack(side="left", padx=10)
        r1 = tk.Frame(cp, bg=T["BG2"])
        r1.pack(fill="x", padx=8, pady=4)
        ui.label(r1, "Max MB/fisier:").pack(side="left", padx=8)
        ui.entry(r1, self.max_mb, width=6).pack(side="left")
        ui.label(r1, "  Exclude foldere:").pack(side="left", padx=8)
        ui.entry(r1, self.excl, width=60).pack(side="left", fill="x", expand=True, padx=4)

        bf = tk.Frame(top, bg=T["BG2"])
        bf.pack(fill="x", padx=12, pady=6)
        ui.btn(bf, "🔍 Scaneaza Folder (F5)", self.do_scan, fg=T["GREEN"]).pack(side="left")
        ui.btn(bf, "📋 Rezumat Folder", self.folder_summary, fg=T["TEAL"]).pack(side="left", padx=6)
        ui.btn(bf, "🕸 Link Map pentru folder", self.linkmap_here, fg=T["PURPLE"]).pack(side="left", padx=6)
        ui.btn(bf, "🔗 URL-urile din cod → Link Checker", self.urls_to_checker, fg=T["ORANGE"]).pack(side="left", padx=6)
        ui.btn(bf, "🔧 Filtru extensii", self.app_filter, fg=T["YELLOW"]).pack(side="left", padx=6)

        tf = ui.lframe(top, "Fisiere Gasite")
        tf.pack(fill="both", expand=True, padx=12, pady=4)
        self.tree = ui.tree(tf, [("path", "PATH", 520, "w"), ("ext", "EXT", 70, "center"), ("size", "SIZE", 90, "e"),
                                 ("lines", "LINES", 70, "e"), ("md5", "MD5", 230, "w")], height=14)
        self.tree.tag_configure("bin", foreground=T["TEXT3"])
        self.tree.tag_configure("off", foreground=T["SEP"])
        self.tree.bind("<Double-1>", lambda e: self._open_selected())

        ef = ui.lframe(top, "Export")
        ef.pack(fill="x", padx=12, pady=(4, 10))
        ef.columnconfigure(1, weight=1)
        ui.label(ef, "Director:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ui.entry(ef, self.out_dir, width=64).grid(row=0, column=1, sticky="ew", padx=4)
        ui.btn(ef, "📂", lambda: self.out_dir.set(filedialog.askdirectory() or self.out_dir.get()), padx=8).grid(row=0, column=2, padx=6)
        ui.label(ef, "Nume fisier:").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ui.entry(ef, self.out_name, width=40).grid(row=1, column=1, sticky="w", padx=4)
        ui.label(ef, "Format:").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        fr = tk.Frame(ef, bg=T["BG2"])
        fr.grid(row=2, column=1, sticky="w")
        for fmt in exporter.FORMATS:
            ui.radio(fr, fmt, self.out_fmt, fmt).pack(side="left", padx=8)
        opt = tk.Frame(ef, bg=T["BG2"])
        opt.grid(row=3, column=0, columnspan=3, sticky="w", padx=4, pady=2)
        ui.label(opt, "Optiuni:").pack(side="left", padx=4)
        for text, var, tip in (("Header", self.add_header, "Header cu metadata"), ("TOC", self.add_toc, "Cuprins (clicabil in HTML)"),
                               ("Stats", self.add_stats, "Statistici pe extensii"), ("MD5", self.add_md5, "Hash MD5 per fisier"),
                               ("Nr. linii", self.add_lnum, "Numerotare linii"), ("Comprima WS", self.compress_ws, "Elimina liniile goale consecutive"),
                               ("Include binare", self.inc_binary, "Exporta si fisierele binare (implicit sunt listate dar sarite)"),
                               ("🔒 Redacteaza secrete", self.redact, "Mascheaza parole, tokenuri, chei API, connection strings.\nRecomandat inainte de a lipi exportul intr-un AI."),
                               ("🕸 Anexa Link Map", self.add_linkmap, "Adauga la final harta legaturilor (URL-uri, importuri, cai, DB, SSO)")):
            ui.chk(opt, text, var, tip).pack(side="left", padx=5)
        sz = tk.Frame(ef, bg=T["BG3"])
        sz.grid(row=4, column=0, columnspan=3, sticky="ew", padx=4, pady=(4, 2))
        ui.label(sz, "📊 Dimensiune estimata:", fg=T["ACCENT"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=5)
        self.size_lbl = ui.label(sz, "— scaneaza mai intai —", fg=T["TEXT3"], font=("Segoe UI", 9, "italic"))
        self.size_lbl.pack(side="left", padx=4)
        sp = tk.Frame(ef, bg=T["BG2"])
        sp.grid(row=5, column=0, columnspan=3, sticky="ew", padx=4, pady=2)
        build_split_row(self.app, sp)
        br = tk.Frame(ef, bg=T["BG2"])
        br.grid(row=6, column=0, columnspan=3, sticky="w", padx=4, pady=6)
        ui.btn(br, "💾 Exporta (Ctrl+S)", self.do_export, fg=T["GREEN"]).pack(side="left")
        ui.btn(br, "📦 Export + ZIP", lambda: self.do_export(zip_it=True), fg=T["PURPLE"]).pack(side="left", padx=6)
        ui.btn(br, "✉ Exporta + Email", lambda: self.do_export(email=True), primary=True).pack(side="left", padx=6)
        ui.btn(br, "✉ Trimite ultimul export", self.email_last).pack(side="left", padx=6)
        lr = tk.Frame(ef, bg=T["BG2"])
        lr.grid(row=7, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 6))
        ui.label(lr, "Ultimul export:").pack(side="left", padx=8)
        self.last_lbl = ui.label(lr, "—", fg=T["TEXT3"], font=("Segoe UI", 8))
        self.last_lbl.pack(side="left", padx=4)
        self.btn_copy = ui.btn(lr, "📋 Copy Path", lambda: self.copy_path(self.last_export), padx=8, pady=3)
        self.btn_copy.pack(side="left", padx=4)
        self.btn_open = ui.btn(lr, "📂 Deschide Folder", lambda: reveal(self.last_export) if self.last_export else None, padx=8, pady=3)
        self.btn_open.pack(side="left", padx=4)
        self.btn_file = ui.btn(lr, "📄 Deschide fisier", lambda: open_path(self.last_export) if self.last_export else None, padx=8, pady=3)
        self.btn_file.pack(side="left", padx=4)
        for b in (self.btn_copy, self.btn_open, self.btn_file):
            b.configure(state="disabled")

    def _toggle_custom(self) -> None:
        if self.scan_mode.get() == "custom":
            self.custom_panel.pack(fill="x", padx=12, pady=4)
        else:
            self.custom_panel.pack_forget()

    # ── presets ──────────────────────────────────────────────────────────────
    def refresh_presets(self) -> None:
        self.preset_cb["values"] = [PRESET_NONE] + [p["name"] for p in self.app.export_pairs]
        self.preset.set(PRESET_NONE)
        self.preset_info.config(text="")

    def _on_preset(self, _e=None) -> None:
        pair = next((p for p in self.app.export_pairs if p["name"] == self.preset.get()), None)
        if not pair:
            self.preset_info.config(text="")
            return
        ok = Path(pair["source"]).exists()
        src = pair["source"]
        self.preset_info.config(text=f"{'✅' if ok else '❌'} {('...' + src[-45:]) if len(src) > 48 else src}",
                                fg=self.T["GREEN"] if ok else self.T["RED"])

    def load_preset(self) -> None:
        pair = next((p for p in self.app.export_pairs if p["name"] == self.preset.get()), None)
        if not pair:
            messagebox.showwarning("Preconfiguratie", "Selecteaza mai intai o pereche din lista!")
            return
        self.folder.set(pair["source"])
        self.out_dir.set(pair["export"])
        self.out_name.set(pair["name"])
        self.app.log(f"✅ Preconfiguratie incarcata: [{pair['name']}] {pair['source']} → {pair['export']}", "ok")
        self.app.select_tab("code")
        if not Path(pair["source"]).exists():
            messagebox.showwarning("Sursa inexistenta", f"Folderul sursa nu exista:\n{pair['source']}")

    # ── scan ────────────────────────────────────────────────────────────────
    def pick_folder(self) -> None:
        d = filedialog.askdirectory(title="Alege folder sursa")
        if d:
            self.folder.set(d)

    def scan_options(self) -> ScanOptions:
        if self.scan_mode.get() == "full":
            return ScanOptions.full(respect_gitignore=self.gitignore.get())
        try:
            max_b = int(float(self.max_mb.get().replace(",", ".")) * MB)
        except ValueError:
            max_b = 5 * MB
        return ScanOptions(recursive=self.recursive.get(), skip_hidden=self.skip_hidden.get(), max_bytes=max_b,
                           excluded={x.strip() for x in self.excl.get().split(",") if x.strip()},
                           respect_gitignore=self.gitignore.get())

    def do_scan(self, then_export: bool = False) -> None:
        folder = self.folder.get().strip().strip('"')
        if not folder:
            if then_export:
                self.app.show_window()
            messagebox.showerror("Eroare", "Alege un folder sursa!")
            return
        root = Path(folder)
        if not root.exists():
            messagebox.showerror("Eroare", f"Folderul nu exista:\n{root}")
            return
        if self.busy:
            return
        self.busy = True
        opts = self.scan_options()
        md5 = self.add_md5.get()
        workers = int(self.app.cfg.get("md5_workers", 4) or 4)
        self.app.set_status("Scanare in curs…", 0)
        self.app.log(f"Scan pornit: {root}")

        def work():
            files = scan_folder(root, opts, progress=lambda n: self.app.call(self.app.set_status, f"Scanare… {n} fisiere"))
            infos = enrich(files, root, with_md5=md5, workers=workers)
            self.files_all = files
            self.app.call(self._populate, infos, root)
            self.busy = False
            if then_export:
                self.app.call(self.do_export)
        self.app.run_bg(work, name="scan")

    def active_exts(self) -> set:
        return {e for e, v in self.app.ext_vars.items() if v.get()}

    def _populate(self, infos, root: Path) -> None:
        self.tree.delete(*self.tree.get_children())
        active = self.active_exts()
        for i in infos:
            tag = "bin" if i.binary else ("" if matches_exts(i.path, active) else "off")
            self.tree.insert("", "end", values=(i.rel, i.ext, f"{i.size / 1024:.1f} KB",
                                                i.lines if i.lines is not None else "-", i.md5 or "-"), tags=(tag,))
        self.update_estimate()
        sel = len(self.selected_files())
        self.app.set_status(f"Scanare completa — {len(infos)} fisiere gasite, {sel} incluse de filtrul de extensii.", 100)
        self.app.log(f"Gasite {len(infos)} fisiere ({sel} pentru export).", "ok")
        if hasattr(self.top, "rebind_wheel"):
            self.top.rebind_wheel()

    def selected_files(self) -> List[Path]:
        active = self.active_exts()
        if not active:
            return list(self.files_all)
        return [fp for fp in self.files_all if matches_exts(fp, active)]

    def update_estimate(self) -> None:
        if self.files_all:
            self.size_lbl.config(text=exporter.estimate(self.selected_files()), fg=self.T["TEAL"])

    def _open_selected(self) -> None:
        sel = self.tree.selection()
        if sel:
            open_path(Path(self.folder.get()) / self.tree.item(sel[0], "values")[0])

    def app_filter(self) -> None:
        self.app.tab_settings.open_filter_dialog()

    # ── export ──────────────────────────────────────────────────────────────
    def export_settings(self) -> exporter.ExportSettings:
        return exporter.ExportSettings(header=self.add_header.get(), toc=self.add_toc.get(), stats=self.add_stats.get(),
                                       md5=self.add_md5.get(), line_numbers=self.add_lnum.get(),
                                       compress_ws=self.compress_ws.get(), redact=self.redact.get(),
                                       include_binary=self.inc_binary.get(), split_bytes=current_split_bytes(self.app))

    def do_export(self, zip_it: bool = False, email: bool = False) -> None:
        files = self.selected_files()
        if not files:
            messagebox.showinfo("Info", "Niciun fisier pentru export.\nScaneaza un folder (F5) si verifica filtrul de extensii.")
            return
        out_dir = Path(self.out_dir.get().strip().strip('"') or default_desktop())
        name = self.out_name.get().strip() or "NexusX_Export"
        fmt = self.out_fmt.get()
        root = Path(self.folder.get())
        st = self.export_settings()
        with_map = self.add_linkmap.get()
        self.app.set_status("Export in curs…", 0)
        self.app.log("═" * 50, "title")
        self.app.log(f" EXPORT START — {len(files)} fisiere → {out_dir / (name + fmt)}", "title")

        def work():
            out_dir.mkdir(parents=True, exist_ok=True)
            if with_map:
                self.app.call(self.app.set_status, "Generare Link Map pentru anexa…")
                res = linkmap.analyse([(root.name, root)], self.scan_options(), redact_secrets=st.redact)
                st.appendix_md = linkmap.to_markdown(res)
            result = exporter.export_files(out_dir / f"{name}{fmt}", fmt, files, root, name, st,
                                           progress=lambda d, t: self.app.call(self.app.set_status, f"Export… {d}/{t}", 100 * d / max(1, t)))
            parts = list(result.parts)
            if zip_it:
                zp = exporter.zip_parts(parts, out_dir / f"{name}.zip")
                parts_for_mail = [zp]
                self.app.call(self.app.log, f"📦 ZIP creat: {zp}", "ok")
            else:
                parts_for_mail = parts
            self.app.call(self._export_done, result, parts_for_mail, name, root, email)
        self.app.run_bg(work, name="export")

    def _export_done(self, result: exporter.ExportResult, mail_parts: List[Path], name: str, root: Path, email: bool) -> None:
        self.last_parts = mail_parts
        self.last_export = result.parts[0] if result.parts else None
        self.last_stats = {"Sursa": str(root), "Fisiere exportate": result.files_written, "Parti": len(result.parts),
                           "Marime": f"{result.total_bytes / MB:.2f} MB", "Secrete redactate": result.redactions,
                           "Binare sarite": len(result.skipped_binary),
                           "Data": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.app.last_outputs = list(mail_parts)
        for p in result.parts:
            self.app.log(f"✅ Export salvat: {p}", "ok")
        if result.redactions:
            self.app.log(f"🔒 {result.redactions} valori sensibile mascate.", "ok")
        if result.skipped_binary:
            self.app.log(f"ℹ {len(result.skipped_binary)} fisiere binare listate dar nu exportate.")
        if self.last_export:
            s = str(self.last_export)
            self.last_lbl.config(text=("..." + s[-60:]) if len(s) > 63 else s, fg=self.T["GREEN"])
            for b in (self.btn_copy, self.btn_open, self.btn_file):
                b.configure(state="normal")
        self.app.set_status(f"Export finalizat: {len(result.parts)} {'parte' if len(result.parts) == 1 else 'parti'} · "
                            f"{result.total_bytes / MB:.2f} MB", 100)
        self.app.notify("Export finalizat", f"{name}: {len(result.parts)} fisier(e)")
        if email:
            self.email_last()
            return
        msg = f"Export finalizat!\n{len(result.parts)} fisier(e):\n" + "".join(f"  • {p.name}\n" for p in result.parts[:6])
        if len(result.parts) > 6:
            msg += f"  … si inca {len(result.parts) - 6}\n"
        msg += f"\nSecrete mascate: {result.redactions} · Binare sarite: {len(result.skipped_binary)}"
        messagebox.showinfo("Export Finalizat", msg)

    def email_last(self) -> None:
        if not self.last_parts:
            messagebox.showinfo("Email", "Nu exista inca un export. Apasa 'Exporta' sau 'Exporta + Email'.")
            return
        e = self.app.cfg.email()
        lang = self.app.cfg.get("language_email", "de")
        label = self.out_name.get() or "NexusX Export"
        html_body = mailer.build_code_html(label, self.last_parts, self.last_stats, lang, e.get("signature") or mailer.default_signature())
        self.app.send_mail(f"{e.get('subject_code', 'NexusX Code Export')}: {label}", html_body, self.last_parts, "Email export cod")

    def copy_path(self, path: Optional[Path]) -> None:
        if not path:
            return
        self.app.clipboard_clear()
        self.app.clipboard_append(str(path))
        self.app.set_status(f"✅ Path copiat: {path}")

    # ── summary / link map ───────────────────────────────────────────────────
    def folder_summary(self) -> None:
        folder = self.folder.get().strip().strip('"')
        if not folder or not Path(folder).exists():
            messagebox.showerror("Eroare", "Alege mai intai un folder sursa valid!")
            return
        root = Path(folder)
        T, ui = self.T, self.ui
        dlg = tk.Toplevel(self.app)
        dlg.title("Rezumat Folder — Optiuni")
        dlg.configure(bg=T["BG1"])
        dlg.geometry("540x430")
        dlg.transient(self.app)
        dlg.grab_set()
        tk.Label(dlg, text="📋 Rezumat Folder — Optiuni", bg=T["BG1"], fg=T["ACCENT"], font=("Segoe UI", 12, "bold")).pack(pady=(16, 8))
        opts = {k: tk.BooleanVar(value=v) for k, v in SUMMARY_DEFAULTS.items()}
        for k, lbl in SUMMARY_OPTIONS.items():
            ui.chk(dlg, lbl, opts[k]).pack(anchor="w", padx=24, pady=2)
        fmt_var = tk.StringVar(value=".md")
        fr = tk.Frame(dlg, bg=T["BG1"])
        fr.pack(fill="x", padx=24, pady=8)
        ui.label(fr, "Format:").pack(side="left")
        for f in (".md", ".txt", ".html", ".json"):
            ui.radio(fr, f, fmt_var, f).pack(side="left", padx=8)

        def run():
            dlg.destroy()
            out_dir = Path(self.out_dir.get() or default_desktop())
            out = out_dir / f"FolderSummary_{root.name}_{datetime.datetime.now():%Y%m%d_%H%M%S}{fmt_var.get()}"
            values = {k: v.get() for k, v in opts.items()}
            self.app.set_status("Generare rezumat…")

            def work():
                p = build_summary(root, out, fmt_var.get(), values, redact_secrets=self.redact.get(),
                                  log=lambda m: self.app.call(self.app.log, m, "ok"))
                self.app.call(self._summary_done, p)
            self.app.run_bg(work, name="summary")
        bf = tk.Frame(dlg, bg=T["BG1"])
        bf.pack(pady=12)
        ui.btn(bf, "▶ Genereaza Rezumat", run, fg=T["GREEN"]).pack(side="left", padx=8)
        ui.btn(bf, "❌ Anuleaza", dlg.destroy, fg=T["RED"]).pack(side="left", padx=8)

    def _summary_done(self, p: Path) -> None:
        self.last_export = p
        self.last_parts = [p]
        self.last_stats = {"Rezumat": p.name}
        self.last_lbl.config(text=str(p), fg=self.T["GREEN"])
        for b in (self.btn_copy, self.btn_open, self.btn_file):
            b.configure(state="normal")
        self.app.set_status(f"Rezumat generat: {p.name}", 100)
        messagebox.showinfo("Rezumat Folder", f"Rezumat generat:\n{p}")

    def linkmap_here(self) -> None:
        folder = self.folder.get().strip().strip('"')
        if not folder or not Path(folder).exists():
            messagebox.showerror("Eroare", "Alege mai intai un folder sursa valid!")
            return
        self.app.select_tab("linkmap")
        self.app.tab_linkmap.run(projects=[(Path(folder).name, Path(folder))])

    def urls_to_checker(self) -> None:
        folder = self.folder.get().strip().strip('"')
        if not folder or not Path(folder).exists():
            messagebox.showerror("Eroare", "Alege mai intai un folder sursa valid!")
            return
        root = Path(folder)
        self.app.set_status("Colectare URL-uri din cod…")

        def work():
            res = linkmap.analyse([(root.name, root)], self.scan_options(), redact_secrets=True)
            self.app.call(self.app.tab_links.add_from_linkmap, res)
        self.app.run_bg(work, name="urls")


class ManagerTab:
    """🚀 Export Manager (UCeX) — source → destination pairs, batch export, Link Map, e-mail."""

    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.fmt = tk.StringVar(value=".txt")
        self.sel_all = tk.BooleanVar(value=False)
        self.email_after = tk.BooleanVar(value=False)
        self.with_map = tk.BooleanVar(value=False)
        self.running = False
        self.last_out: Optional[Path] = None
        self.last_parts: List[Path] = []
        self.prog = tk.DoubleVar(value=0)
        self._build(frame)

    @property
    def pairs(self) -> List[Dict[str, str]]:
        return self.app.export_pairs

    def _build(self, frame) -> None:
        ui, T = self.ui, self.T
        top = make_scrollable(frame, T)
        ui.label(top, "🚀 Export Manager — Perechi Sursa → Destinatie", fg=T["ACCENT"], font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        ui.label(top, "Dublu-click pe o pereche pentru editare. Starea sursei e verificata live.", fg=T["TEXT3"]).pack(anchor="w", padx=14)
        tb = tk.Frame(top, bg=T["BG2"])
        tb.pack(fill="x", padx=12, pady=6)
        for text, cmd, col in (("➕ Adauga", self.add, "GREEN"), ("✏️ Editeaza", self.edit, "YELLOW"), ("🗑️ Sterge", self.delete, "RED"),
                               ("⬆", lambda: self.move(-1), "TEXT1"), ("⬇", lambda: self.move(1), "TEXT1"),
                               ("💾 Salveaza Config", self.save_cfg, "TEAL"), ("📂 Incarca Config", self.load_cfg, "PURPLE")):
            ui.btn(tb, text, cmd, fg=T[col]).pack(side="left", padx=3)
        lf = ui.lframe(top, "Perechi Configurate")
        lf.pack(fill="both", expand=True, padx=12, pady=4)
        self.tree = ui.tree(lf, [("name", "NAME", 160, "w"), ("source", "SOURCE", 400, "w"), ("export", "EXPORT", 400, "w"),
                                 ("status", "STATUS", 140, "center")], height=10, selectmode="extended")
        for tag, col in (("ok", "GREEN"), ("error", "RED"), ("running", "YELLOW")):
            self.tree.tag_configure(tag, foreground=T[col])
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.refresh()

        of = ui.lframe(top, "Optiuni Export Manager")
        of.pack(fill="x", padx=12, pady=4)
        r = tk.Frame(of, bg=T["BG2"])
        r.pack(fill="x", padx=8, pady=6)
        ui.label(r, "Format:").pack(side="left", padx=6)
        for f in exporter.FORMATS:
            ui.radio(r, f, self.fmt, f).pack(side="left", padx=5)
        ui.chk(r, "Selecteaza toate", self.sel_all, "Bifat = exporta TOATE perechile. Debifat = doar cele selectate (multi-select cu Ctrl).").pack(side="left", padx=14)
        ui.chk(r, "🕸 Anexa Link Map", self.with_map, "Adauga harta legaturilor fiecarui proiect la final").pack(side="left", padx=6)
        ui.chk(r, "✉ Email la final", self.email_after, "Trimite automat exporturile pe email dupa rulare").pack(side="left", padx=6)
        sp = tk.Frame(top, bg=T["BG2"])
        sp.pack(fill="x", padx=12, pady=2)
        build_split_row(self.app, sp)
        bf = tk.Frame(top, bg=T["BG2"])
        bf.pack(fill="x", padx=12, pady=6)
        ui.btn(bf, "🚀 Ruleaza Export(uri)", self.run, fg=T["GREEN"]).pack(side="left")
        ui.btn(bf, "🔍 Verifica Cai", self.verify, fg=T["TEAL"]).pack(side="left", padx=6)
        ui.btn(bf, "🕸 Link Map pentru perechi", self.linkmap_pairs, fg=T["PURPLE"]).pack(side="left", padx=6)
        ui.btn(bf, "✉ Trimite ultimele exporturi", self.email, primary=True).pack(side="left", padx=6)
        ui.btn(bf, "🗑️ Clear Log", self.clear_log, fg=T["RED"]).pack(side="left", padx=6)
        lr = tk.Frame(top, bg=T["BG2"])
        lr.pack(fill="x", padx=12, pady=(0, 4))
        ui.label(lr, "Ultimul export:").pack(side="left", padx=8)
        self.last_lbl = ui.label(lr, "—", fg=T["TEXT3"], font=("Segoe UI", 8))
        self.last_lbl.pack(side="left", padx=4)
        ui.btn(lr, "📋 Copy Path", lambda: self.app.tab_code.copy_path(self.last_out), padx=8, pady=3).pack(side="left", padx=4)
        ui.btn(lr, "📂 Deschide Folder Export", lambda: reveal(self.last_out) if self.last_out else None, padx=8, pady=3).pack(side="left", padx=4)
        pf = tk.Frame(top, bg=T["BG3"])
        pf.pack(fill="x", padx=12, pady=(2, 0))
        ui.label(pf, "📊 Progres export:", fg=T["ACCENT"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=10, pady=4)
        self.prog_lbl = ui.label(pf, "", fg=T["TEXT3"], font=("Segoe UI", 8, "italic"))
        self.prog_lbl.pack(side="left")
        from tkinter import ttk
        ttk.Progressbar(pf, variable=self.prog, maximum=100, length=320).pack(side="right", padx=10, pady=4)
        elf = ui.lframe(top, "Log Export Manager")
        elf.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        fr, self.log_txt = ui.scrolled_text(elf, height=9)
        fr.pack(fill="both", expand=True, padx=4, pady=4)

    # ── list management ──
    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for p in self.pairs:
            ok = Path(p["source"]).exists()
            self.tree.insert("", "end", values=(p["name"], p["source"], p["export"], "✅ OK" if ok else "⚠️ Sursa lipseste"),
                             tags=("ok" if ok else "error",))
        if hasattr(self.app, "tab_code"):
            self.app.tab_code.refresh_presets()

    def persist(self) -> None:
        self.app.cfg.set_export_pairs(self.pairs)
        self.refresh()

    def log(self, msg: str, tag: str = "info") -> None:
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n", tag)
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")
        self.app.log(f"[EM] {msg}", "error" if tag == "error" else ("warn" if tag == "warn" else "info"))

    def clear_log(self) -> None:
        self.log_txt.configure(state="normal")
        self.log_txt.delete("1.0", "end")
        self.log_txt.configure(state="disabled")

    def selected_indices(self) -> List[int]:
        return [self.tree.index(i) for i in self.tree.selection()]

    def add(self) -> None:
        self._dialog(None)

    def edit(self) -> None:
        idx = self.selected_indices()
        if not idx:
            messagebox.showinfo("Info", "Selecteaza o pereche din lista.")
            return
        self._dialog(idx[0])

    def delete(self) -> None:
        idx = self.selected_indices()
        if not idx:
            return
        names = ", ".join(self.pairs[i]["name"] for i in idx)
        if messagebox.askyesno("Confirma", f"Stergi perechea/perechile: {names}?"):
            for i in sorted(idx, reverse=True):
                self.pairs.pop(i)
            self.persist()

    def move(self, d: int) -> None:
        idx = self.selected_indices()
        if len(idx) != 1:
            return
        i, j = idx[0], idx[0] + d
        if 0 <= j < len(self.pairs):
            self.pairs[i], self.pairs[j] = self.pairs[j], self.pairs[i]
            self.persist()
            self.tree.selection_set(self.tree.get_children()[j])

    def _dialog(self, idx: Optional[int]) -> None:
        T, ui = self.T, self.ui
        dlg = tk.Toplevel(self.app)
        dlg.title("Editeaza Pereche" if idx is not None else "Adauga Pereche")
        dlg.configure(bg=T["BG1"])
        dlg.geometry("760x220")
        dlg.transient(self.app)
        dlg.grab_set()
        pair = self.pairs[idx] if idx is not None else {"name": "", "source": "", "export": ""}
        vs = {k: tk.StringVar(value=pair.get(k, "")) for k in ("name", "source", "export")}
        for r, (lbl, key, browse) in enumerate((("Nume:", "name", False), ("Sursa:", "source", True), ("Export:", "export", True))):
            tk.Label(dlg, text=lbl, bg=T["BG1"], fg=T["TEXT2"]).grid(row=r, column=0, sticky="w", padx=12, pady=8)
            ui.entry(dlg, vs[key], width=70).grid(row=r, column=1, sticky="ew", padx=4, pady=8)
            if browse:
                ui.btn(dlg, "📂", lambda v=vs[key]: v.set(filedialog.askdirectory() or v.get()), padx=8).grid(row=r, column=2, padx=6)
        dlg.columnconfigure(1, weight=1)

        def save():
            new = {k: v.get().strip().strip('"') for k, v in vs.items()}
            if not new["name"]:
                messagebox.showerror("Eroare", "Numele nu poate fi gol!", parent=dlg)
                return
            if not new["export"] and new["source"]:
                new["export"] = str(Path(new["source"]).parent / "codeexport" / new["name"])
            if idx is not None:
                self.pairs[idx] = new
            else:
                self.pairs.append(new)
            self.persist()
            dlg.destroy()
        bf = tk.Frame(dlg, bg=T["BG1"])
        bf.grid(row=3, column=0, columnspan=3, pady=10)
        ui.btn(bf, "💾 Salveaza", save, fg=T["GREEN"]).pack(side="left", padx=8)
        ui.btn(bf, "❌ Anuleaza", dlg.destroy, fg=T["RED"]).pack(side="left", padx=8)

    def save_cfg(self) -> None:
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="ucex_export_pairs.json")
        if p:
            Path(p).write_text(json.dumps(self.pairs, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log(f"Config salvat: {p}", "ok")

    def load_cfg(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p:
            return
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("format invalid (se asteapta o lista de perechi)")
            self.app.export_pairs[:] = [dict(name=d.get("name", ""), source=d.get("source", ""), export=d.get("export", "")) for d in data]
            self.persist()
            self.log(f"Config incarcat: {p} ({len(data)} perechi)", "ok")
        except Exception as e:  # noqa: BLE001
            self.log(f"Eroare: {e}", "error")

    def verify(self) -> None:
        self.log("─── Verificare cai ───", "section")
        for p in self.pairs:
            s, e = Path(p["source"]), Path(p["export"])
            self.log(f"[{p['name']}] Sursa: {'✅' if s.exists() else '❌ LIPSESTE'} | Export: {'✅' if e.exists() else '⚠️ Va fi creat'}")
        self.refresh()

    def _targets(self) -> List[Dict[str, str]]:
        if self.sel_all.get():
            return list(self.pairs)
        idx = self.selected_indices()
        return [self.pairs[i] for i in idx]

    # ── run ──
    def run(self) -> None:
        if self.running:
            self.log("Export deja in curs!", "warn")
            return
        pairs = self._targets()
        if not pairs:
            if not self.app.winfo_viewable():
                pairs = list(self.pairs)  # from tray: run all
            else:
                messagebox.showinfo("Info", "Selecteaza perechi din lista sau bifeaza 'Selecteaza toate'.")
                return
        self.running = True
        fmt = self.fmt.get()
        code = self.app.tab_code
        st_base = code.export_settings()
        active = code.active_exts()
        with_map, email = self.with_map.get(), self.email_after.get()
        self.prog.set(0)

        def status(i, text, tag):
            items = self.tree.get_children()
            name = pairs[i]["name"]
            for it in items:
                if self.tree.item(it, "values")[0] == name:
                    vals = list(self.tree.item(it, "values"))
                    vals[3] = text
                    self.tree.item(it, values=vals, tags=(tag,))

        def work():
            total = len(pairs)
            self.app.call(self.log, f"══ Start Export Manager — {total} perechi ══", "title")
            written_all: List[Path] = []
            for i, pair in enumerate(pairs):
                src, exp, name = Path(pair["source"]), Path(pair["export"]), pair["name"]
                self.app.call(self.log, f"[{i + 1}/{total}] {name}: {src} → {exp}")
                if not src.exists():
                    self.app.call(self.log, f"  ❌ Sursa nu exista: {src}", "error")
                    self.app.call(status, i, "❌ Sursa lipseste", "error")
                    continue
                try:
                    self.app.call(status, i, "⏳ Running...", "running")
                    files = [f for f in scan_folder(src, ScanOptions.full()) if matches_exts(f, active)]
                    self.app.call(self.log, f"  📁 {len(files)} fisiere gasite")
                    st = exporter.ExportSettings(**{**st_base.__dict__})
                    if with_map:
                        st.appendix_md = linkmap.to_markdown(linkmap.analyse([(name, src)], redact_secrets=st.redact))
                    out = exp / f"{name}_{datetime.datetime.now():%Y%m%d_%H%M%S}{fmt}"
                    res = exporter.export_files(out, fmt, files, src, name, st)
                    for p in res.parts:
                        self.app.call(self.log, f"  ✅ Exportat: {p}", "ok")
                    if len(res.parts) > 1:
                        self.app.call(self.log, f"  📦 Split: {len(res.parts)} parti.", "ok")
                    if res.redactions:
                        self.app.call(self.log, f"  🔒 {res.redactions} secrete mascate.", "ok")
                    written_all.extend(res.parts)
                    self.last_out = res.parts[0]
                    self.app.call(status, i, "✅ Done", "ok")
                except Exception as e:  # noqa: BLE001
                    self.app.call(self.log, f"  ❌ Eroare: {e}", "error")
                    self.app.call(status, i, "❌ Eroare", "error")
                pct = (i + 1) / total * 100
                self.app.call(self.prog.set, pct)
                self.app.call(self.prog_lbl.configure, text=f"{i + 1}/{total} perechi ({pct:.0f}%)")
            self.running = False
            self.last_parts = written_all
            self.app.call(self._done, total, email)
        self.app.run_bg(work, name="export-manager")

    def _done(self, total: int, email: bool) -> None:
        self.log("══ Export Manager Finalizat ══", "title")
        if self.last_out:
            self.last_lbl.config(text=str(self.last_out), fg=self.T["GREEN"])
        self.app.last_outputs = list(self.last_parts)
        self.app.notify("Export Manager", f"Finalizat pentru {total} perechi")
        if email and self.last_parts:
            self.email()
        elif self.app.winfo_viewable():
            messagebox.showinfo("Export Manager", f"Export finalizat pentru {total} perechi!")

    def email(self) -> None:
        if not self.last_parts:
            messagebox.showinfo("Email", "Ruleaza mai intai Export Manager.")
            return
        e = self.app.cfg.email()
        stats = {"Exporturi": len(self.last_parts), "Data": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
        html_body = mailer.build_code_html("Export Manager", self.last_parts, stats, self.app.cfg.get("language_email", "de"),
                                           e.get("signature") or mailer.default_signature())
        self.app.send_mail(f"{e.get('subject_code', 'NexusX Code Export')}: Export Manager", html_body, self.last_parts,
                           "Email Export Manager")

    def linkmap_pairs(self) -> None:
        pairs = self._targets() or list(self.pairs)
        self.app.select_tab("linkmap")
        self.app.tab_linkmap.run(projects=[(p["name"], Path(p["source"])) for p in pairs])
