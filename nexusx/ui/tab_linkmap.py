# -*- coding: utf-8 -*-
"""Tab: 🕸 Link Map — connections between the user's tools, browsers, company systems."""
from __future__ import annotations

import datetime
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

from .. import mailer
from ..codex import linkmap
from .widgets import open_path


class LinkMapTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.result: Optional[linkmap.LinkMapResult] = None
        self.saved: List[Path] = []
        self.scope = tk.StringVar(value="all")
        self.kind = tk.StringVar(value="(toate)")
        self.query = tk.StringVar()
        self.only_cross = tk.BooleanVar(value=False)
        self.hide_imports = tk.BooleanVar(value=True)
        self.running = False
        self._build(frame)

    def _build(self, frame) -> None:
        ui, T = self.ui, self.T
        head = tk.Frame(frame, bg=T["BG2"])
        head.pack(fill="x", padx=12, pady=(10, 2))
        ui.label(head, "🕸 Link Map — cum se leaga tool-urile tale intre ele si de sistemele firmei",
                 fg=T["ACCENT"], font=("Segoe UI", 11, "bold")).pack(side="left")
        ui.label(frame, "Analiza statica a codului: URL-uri, importuri, ProjectReference, cai/UNC, baze de date, SSO/OAuth, "
                        "COM (Outlook/Excel/SAP), Selenium/Playwright, Apps Script, variabile de mediu, endpoint-uri.",
                 fg=T["TEXT3"], wraplength=1300, justify="left").pack(anchor="w", padx=14)
        bar = tk.Frame(frame, bg=T["BG2"])
        bar.pack(fill="x", padx=12, pady=6)
        ui.label(bar, "Domeniu:").pack(side="left", padx=4)
        for val, lbl in (("all", "Toate perechile Export Manager"), ("selected", "Perechile selectate"), ("folder", "Folderul din Code Export")):
            ui.radio(bar, lbl, self.scope, val).pack(side="left", padx=6)
        ui.btn(bar, "▶ Genereaza Link Map", self.run, primary=True).pack(side="left", padx=10)
        ui.btn(bar, "🔗 URL-uri → Link Checker", self.to_checker, fg=T["ORANGE"]).pack(side="left", padx=4)
        ui.btn(bar, "🌐 Deschide raport HTML", self.open_html, fg=T["TEAL"]).pack(side="left", padx=4)
        ui.btn(bar, "📂 Folder rapoarte", lambda: open_path(self.app.ensure_report_dir())).pack(side="left", padx=4)
        ui.btn(bar, "✉ Email Link Map", self.email, primary=True).pack(side="left", padx=4)

        self.summary = tk.Label(frame, text="Niciun rezultat inca.", bg=T["BG3"], fg=T["TEAL"], font=("Segoe UI", 9, "bold"),
                                anchor="w", padx=10, pady=5)
        self.summary.pack(fill="x", padx=12, pady=(2, 4))

        pan = tk.PanedWindow(frame, orient="horizontal", bg=T["BG2"], sashwidth=6, bd=0)
        pan.pack(fill="both", expand=True, padx=12, pady=4)
        left = tk.Frame(pan, bg=T["BG2"])
        right = tk.Frame(pan, bg=T["BG2"])
        pan.add(left, minsize=360, width=430)
        pan.add(right, minsize=500)

        lf1 = ui.lframe(left, "Legaturi intre proiecte")
        lf1.pack(fill="both", expand=True, pady=(0, 4))
        self.tv_links = ui.tree(lf1, [("from", "DIN", 120, "w"), ("to", "CATRE", 120, "w"), ("n", "NR", 50, "e"),
                                      ("kinds", "TIPURI", 160, "w")], height=8, selectmode="browse")
        lf2 = ui.lframe(left, "Resurse comune (≥2 tool-uri)")
        lf2.pack(fill="both", expand=True)
        self.tv_shared = ui.tree(lf2, [("kind", "TIP", 80, "w"), ("target", "RESURSA", 240, "w"), ("projects", "PROIECTE", 160, "w")],
                                 height=10, selectmode="browse")

        flt = tk.Frame(right, bg=T["BG2"])
        flt.pack(fill="x", pady=(0, 4))
        ui.label(flt, "Tip:").pack(side="left", padx=4)
        cb = ttk.Combobox(flt, textvariable=self.kind, values=["(toate)"] + list(linkmap.KINDS), state="readonly", width=14)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.fill_edges())
        ui.label(flt, "Cauta:").pack(side="left", padx=(10, 4))
        en = ui.entry(flt, self.query, width=30)
        en.pack(side="left")
        en.bind("<KeyRelease>", lambda e: self.fill_edges())
        ui.chk(flt, "Doar legaturi intre proiecte", self.only_cross, command=self.fill_edges).pack(side="left", padx=8)
        ui.chk(flt, "Ascunde importuri stdlib/proprii", self.hide_imports, command=self.fill_edges).pack(side="left", padx=4)
        lf3 = ui.lframe(right, "Toate legaturile")
        lf3.pack(fill="both", expand=True)
        self.tv_edges = ui.tree(lf3, [("project", "PROIECT", 120, "w"), ("kind", "TIP", 90, "w"), ("target", "TINTA", 380, "w"),
                                      ("scope", "SCOPE", 80, "w"), ("resolved", "→ PROIECT", 110, "w"), ("src", "SURSA", 220, "w")],
                                height=20)
        self.tv_edges.tag_configure("cross", foreground=T["YELLOW"])
        self.tv_edges.bind("<Double-1>", self._open_edge)
        self.tv_edges.bind("<Button-3>", self._ctx)

    # ── actions ──
    def _projects_for_scope(self) -> List[Tuple[str, Path]]:
        scope = self.scope.get()
        if scope == "folder":
            f = self.app.tab_code.folder.get().strip().strip('"')
            return [(Path(f).name, Path(f))] if f else []
        if scope == "selected":
            pairs = [self.app.export_pairs[i] for i in self.app.tab_manager.selected_indices()]
        else:
            pairs = list(self.app.export_pairs)
        return [(p["name"], Path(p["source"])) for p in pairs]

    def run(self, projects: Optional[List[Tuple[str, Path]]] = None) -> None:
        if self.running:
            return
        projects = projects or self._projects_for_scope()
        projects = [(n, p) for n, p in projects if p]
        if not projects:
            messagebox.showinfo("Link Map", "Nu exista proiecte de analizat (alege folder sau perechi).")
            return
        # skip a parent folder that contains other projects (e.g. 'myCreativity') when several are analysed
        if len(projects) > 2:
            roots = [Path(p) for _, p in projects]
            projects = [(n, Path(p)) for n, p in projects
                        if not any(o != Path(p) and Path(p) in o.parents for o in roots)]
        self.running = True
        self.app.set_status(f"Link Map: analiza {len(projects)} proiecte…", 0)
        redact = self.app.tab_code.redact.get()

        def work():
            res = linkmap.analyse(projects, redact_secrets=redact,
                                  progress=lambda m: (self.app.call(self.app.log, m), self.app.call(self.app.set_status, m)))
            out_dir = self.app.ensure_report_dir()
            saved = linkmap.save_all(res, out_dir)
            self.app.call(self._done, res, saved)
        self.app.run_bg(work, name="linkmap")

    def _done(self, res: linkmap.LinkMapResult, saved: List[Path]) -> None:
        self.running = False
        self.result, self.saved = res, saved
        links, shared = res.project_links(), res.shared_resources()
        self.summary.config(text=f"{len(res.projects)} proiecte · {len(res.edges)} legaturi · {len(links)} dependente intre proiecte · "
                                 f"{len(shared)} resurse comune · {len(res.unique_urls())} URL-uri unice  —  salvat: {saved[0].parent}")
        self.tv_links.delete(*self.tv_links.get_children())
        for (a, b), es in sorted(links.items()):
            self.tv_links.insert("", "end", values=(a, b, len(es), ", ".join(sorted({e.kind for e in es}))))
        self.tv_shared.delete(*self.tv_shared.get_children())
        for k, t, p in shared[:500]:
            self.tv_shared.insert("", "end", values=(k, t, ", ".join(p)))
        self.fill_edges()
        self.app.last_outputs = list(saved)
        self.app.set_status(f"Link Map gata: {len(res.edges)} legaturi.", 100)
        self.app.log(f"✅ Link Map salvat: {', '.join(p.name for p in saved)}", "ok")
        self.app.notify("Link Map", f"{len(res.edges)} legaturi in {len(res.projects)} proiecte")

    def fill_edges(self) -> None:
        if not self.result:
            return
        k, q = self.kind.get(), self.query.get().lower().strip()
        self.tv_edges.delete(*self.tv_edges.get_children())
        n = 0
        for e in self.result.edges:
            if k != "(toate)" and e.kind != k:
                continue
            if self.only_cross.get() and not e.resolved_project:
                continue
            if self.hide_imports.get() and e.kind == "import" and e.scope in ("stdlib", "own"):
                continue
            if q and q not in f"{e.project} {e.target} {e.file} {e.detail}".lower():
                continue
            self.tv_edges.insert("", "end", values=(e.project, e.kind, e.target, e.scope, e.resolved_project, f"{e.file}:{e.line}"),
                                 tags=("cross",) if e.resolved_project else ())
            n += 1
            if n >= 5000:
                break

    def _edge_path(self) -> Optional[Path]:
        sel = self.tv_edges.selection()
        if not sel or not self.result:
            return None
        proj, _k, _t, _s, _r, src = self.tv_edges.item(sel[0], "values")
        root = next((p.root for p in self.result.projects if p.name == proj), None)
        return (root / src.rsplit(":", 1)[0]) if root else None

    def _open_edge(self, _e=None) -> None:
        p = self._edge_path()
        if p and p.exists():
            open_path(p)

    def _ctx(self, event) -> None:
        iid = self.tv_edges.identify_row(event.y)
        if not iid:
            return
        self.tv_edges.selection_set(iid)
        vals = self.tv_edges.item(iid, "values")
        m = tk.Menu(self.app, tearoff=0, bg=self.T["BG3"], fg=self.T["TEXT1"], activebackground=self.T["ACCENT"])
        m.add_command(label="📄 Deschide fisierul sursa", command=self._open_edge)
        m.add_command(label="📋 Copiaza tinta", command=lambda: (self.app.clipboard_clear(), self.app.clipboard_append(vals[2])))
        if vals[1] == "url":
            m.add_command(label="🔗 Verifica in Link Checker", command=lambda: self.app.tab_links.add_urls([vals[2]], "Link Map"))
        m.tk_popup(event.x_root, event.y_root)

    def to_checker(self) -> None:
        if not self.result:
            messagebox.showinfo("Link Map", "Genereaza mai intai Link Map.")
            return
        self.app.tab_links.add_from_linkmap(self.result)

    def open_html(self) -> None:
        html = next((p for p in self.saved if p.suffix == ".html"), None)
        if html:
            open_path(html)
        else:
            messagebox.showinfo("Link Map", "Genereaza mai intai Link Map.")

    def email(self) -> None:
        if not self.saved or not self.result:
            messagebox.showinfo("Email", "Genereaza mai intai Link Map.")
            return
        e = self.app.cfg.email()
        stats = {"Proiecte": len(self.result.projects), "Legaturi": len(self.result.edges),
                 "Dependente intre proiecte": len(self.result.project_links()),
                 "Resurse comune": len(self.result.shared_resources()), "Data": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
        body = mailer.build_code_html("Link Map", self.saved, stats, self.app.cfg.get("language_email", "de"),
                                      e.get("signature") or mailer.default_signature())
        self.app.send_mail("NexusX Link Map", body, self.saved, "Email Link Map")
