# -*- coding: utf-8 -*-
"""Tabs from UCeX v7: ✂ Split & Merge and 📓 OneNote Extractor."""
from __future__ import annotations

import datetime
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from ..paths import default_desktop
from ..tools import onenote, splitmerge
from .widgets import make_scrollable, open_path


class SplitMergeTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.split_file = tk.StringVar()
        self.split_out = tk.StringVar(value=str(default_desktop() / "NexusX_Split"))
        self.split_size = tk.StringVar(value="100")
        self.split_unit = tk.StringVar(value="MB")
        self.split_mode = tk.StringVar(value="equal")
        self.headers = tk.BooleanVar(value=True)
        self.merge_files: List[str] = []
        self.merge_out = tk.StringVar(value=str(default_desktop() / "NexusX_Merge"))
        self.merge_name = tk.StringVar(value="merged_output")
        self.status = tk.StringVar(value="Gata.")
        self.prog = tk.DoubleVar(value=0)
        self.log_lines: List[str] = []
        self.running = False
        self.last_dir: Optional[Path] = None
        self._build(frame)

    def _build(self, frame) -> None:
        ui, T = self.ui, self.T
        top = make_scrollable(frame, T)
        hdr = tk.Frame(top, bg=T["BG2"])
        hdr.pack(fill="x", padx=12, pady=(10, 0))
        ui.label(hdr, "✂ Split & Merge Engine", fg=T["ACCENT"], font=("Segoe UI", 13, "bold")).pack(side="left", padx=4)
        ui.label(hdr, "Imparte fisiere mari in parti sau combina mai multe fisiere intr-unul singur.", fg=T["TEXT3"]).pack(side="left", padx=8)

        sf = ui.lframe(top, "✂ SPLIT — Imparte un fisier mare in parti mai mici", fg=T["YELLOW"])
        sf.pack(fill="x", padx=12, pady=(8, 6))
        r1 = tk.Frame(sf, bg=T["BG2"])
        r1.pack(fill="x", padx=8, pady=(8, 2))
        ui.label(r1, "Fisier sursa:", width=22, anchor="w").pack(side="left")
        e = ui.entry(r1, self.split_file, width=60)
        e.pack(side="left", padx=4, fill="x", expand=True)
        ui.tooltip(e, "Orice fisier: .onepkg, .txt, .py, export NexusX, .zip, .pdf, .csv …")
        ui.btn(r1, "📂 Browse", self.browse_split_file, fg=T["ACCENT"]).pack(side="left", padx=6)
        ui.btn(r1, "⬅ Ultimul export cod", self.use_last_export).pack(side="left")
        r2 = tk.Frame(sf, bg=T["BG2"])
        r2.pack(fill="x", padx=8, pady=2)
        ui.label(r2, "Folder output:", width=22, anchor="w").pack(side="left")
        ui.entry(r2, self.split_out, width=60).pack(side="left", padx=4, fill="x", expand=True)
        ui.btn(r2, "📂 Browse", lambda: self.split_out.set(filedialog.askdirectory() or self.split_out.get()), fg=T["TEAL"]).pack(side="left", padx=6)
        r3 = tk.Frame(sf, bg=T["BG2"])
        r3.pack(fill="x", padx=8, pady=2)
        ui.label(r3, "Dimensiune maxima / parte:", width=22, anchor="w").pack(side="left")
        ui.entry(r3, self.split_size, width=8).pack(side="left", padx=2)
        for unit in ("MB", "GB", "KB"):
            ui.radio(r3, unit, self.split_unit, unit).pack(side="left", padx=4)
        r4 = tk.Frame(sf, bg=T["BG2"])
        r4.pack(fill="x", padx=8, pady=2)
        ui.label(r4, "Strategie:", width=22, anchor="w").pack(side="left")
        for val, lbl, tip in (("equal", "Parti egale (recomandat)", "Imparte in N parti de dimensiune aproximativ egala."),
                              ("size", "Dimensiune fixa / parte", "Fiecare parte are dimensiunea specificata (ultima poate fi mai mica).")):
            rb = ui.radio(r4, lbl, self.split_mode, val)
            rb.pack(side="left", padx=8)
            ui.tooltip(rb, tip)
        ui.chk(r4, "Antet/subsol pentru fisiere text", self.headers,
               "Bifat (ca in v7): fiecare parte text primeste antetul FISIER MAMA / PARTE / URMATOAREA si\n"
               "„END PART N of M — CONTINUA CU”. Debifat: bytes exacti.").pack(side="left", padx=16)
        r5 = tk.Frame(sf, bg=T["BG2"])
        r5.pack(fill="x", padx=8, pady=(4, 8))
        self.info = ui.label(r5, "", fg=T["TEXT3"], font=("Segoe UI", 8, "italic"))
        self.info.pack(side="left", padx=4)
        ui.btn(r5, "✂ START SPLIT", self.do_split, fg=T["BG1"], bg=T["YELLOW"]).pack(side="right", padx=8)
        for v in (self.split_file, self.split_size, self.split_unit, self.split_mode):
            v.trace_add("write", lambda *_: self.update_info())

        mf = ui.lframe(top, "⧓ MERGE — Combina mai multe fisiere intr-unul singur", fg=T["TEAL"])
        mf.pack(fill="x", padx=12, pady=(4, 6))
        ml = tk.Frame(mf, bg=T["BG2"])
        ml.pack(fill="x", padx=8, pady=(8, 2))
        ui.label(ml, "Fisiere de combinat (acelasi tip):").pack(side="left", padx=(0, 6))
        for text, cmd, col in (("➕ Adauga fisiere", self.add_merge, "TEAL"), ("🧩 Adauga toate partile unui split", self.add_parts_set, "ACCENT"),
                               ("✖ Sterge selectat", self.remove_merge, "RED"), ("⬆ Sus", lambda: self.move(-1), "TEXT2"),
                               ("⬇ Jos", lambda: self.move(1), "TEXT2"), ("🔢 Sorteaza dupa nr. parte", self.sort_parts, "YELLOW"),
                               ("🗑 Goleste lista", self.clear_merge, "TEXT3")):
            ui.btn(ml, text, cmd, fg=T[col], padx=8).pack(side="left", padx=2)
        lbf = tk.Frame(mf, bg=T["BG3"])
        lbf.pack(fill="x", padx=8, pady=2)
        sb = ttk.Scrollbar(lbf, orient="vertical")
        self.lb = tk.Listbox(lbf, yscrollcommand=sb.set, height=7, bg=T["BG3"], fg=T["TEXT1"], selectbackground=T["ACCENT"],
                             font=("Segoe UI", 9), relief="flat", bd=0, selectmode="single")
        sb.config(command=self.lb.yview)
        sb.pack(side="right", fill="y")
        self.lb.pack(fill="x", expand=True)
        mo = tk.Frame(mf, bg=T["BG2"])
        mo.pack(fill="x", padx=8, pady=2)
        ui.label(mo, "Folder output:", width=22, anchor="w").pack(side="left")
        ui.entry(mo, self.merge_out, width=56).pack(side="left", padx=4, fill="x", expand=True)
        ui.btn(mo, "📂 Browse", lambda: self.merge_out.set(filedialog.askdirectory() or self.merge_out.get()), fg=T["TEAL"]).pack(side="left", padx=6)
        mn = tk.Frame(mf, bg=T["BG2"])
        mn.pack(fill="x", padx=8, pady=2)
        ui.label(mn, "Nume fisier rezultat:", width=22, anchor="w").pack(side="left")
        ui.entry(mn, self.merge_name, width=36).pack(side="left", padx=4)
        ui.label(mn, "(extensia se detecteaza automat; marcajele de split se elimina; SHA-256 verificat daca exista manifest)",
                 fg=T["TEXT3"], font=("Segoe UI", 8, "italic")).pack(side="left", padx=4)
        mr = tk.Frame(mf, bg=T["BG2"])
        mr.pack(fill="x", padx=8, pady=(4, 8))
        ui.btn(mr, "⧓ START MERGE", self.do_merge, fg=T["BG1"], bg=T["TEAL"]).pack(side="right", padx=8)

        pf = ui.lframe(top, "Progress & Log")
        pf.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        pr = tk.Frame(pf, bg=T["BG2"])
        pr.pack(fill="x", padx=8, pady=(6, 2))
        ui.label(pr, "Status:").pack(side="left")
        tk.Label(pr, textvariable=self.status, bg=T["BG2"], fg=T["GREEN"], font=("Segoe UI", 9, "italic")).pack(side="left", padx=4)
        ttk.Progressbar(pr, variable=self.prog, maximum=100, length=260).pack(side="right", padx=8)
        fr, self.log_txt = ui.scrolled_text(pf, height=9)
        fr.pack(fill="both", expand=True, padx=8, pady=(2, 4))
        br = tk.Frame(pf, bg=T["BG2"])
        br.pack(fill="x", padx=8, pady=(0, 6))
        ui.btn(br, "🗑 Goleste log", self.clear_log, fg=T["TEXT3"]).pack(side="right", padx=4)
        ui.btn(br, "📋 Copiaza log", self.copy_log, fg=T["ACCENT"]).pack(side="right", padx=4)
        ui.btn(br, "📂 Deschide rezultatul", lambda: open_path(self.last_dir) if self.last_dir else None).pack(side="right", padx=4)

    # ── helpers ──
    def log(self, msg: str, tag: str = "info") -> None:
        line = f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n"
        self.log_lines.append(line)
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", line, tag)
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")
        self.app.log(f"[SM] {msg}", "error" if tag == "error" else ("warn" if tag == "warn" else "info"))

    def tlog(self, msg: str, tag: str = "info") -> None:
        self.app.call(self.log, msg, tag)

    def clear_log(self) -> None:
        self.log_lines.clear()
        self.log_txt.configure(state="normal")
        self.log_txt.delete("1.0", "end")
        self.log_txt.configure(state="disabled")

    def copy_log(self) -> None:
        self.app.clipboard_clear()
        self.app.clipboard_append("".join(self.log_lines))
        self.status.set("Log copiat in clipboard.")

    def browse_split_file(self) -> None:
        p = filedialog.askopenfilename(title="Selecteaza fisierul de split", filetypes=[
            ("Toate fisierele", "*.*"), ("OneNote Package", "*.onepkg"), ("Text", "*.txt *.md *.csv *.log"),
            ("Cod sursa", "*.py *.cs *.js *.ts *.java *.cpp *.c *.h"), ("Archive", "*.zip *.7z *.tar *.gz"), ("PDF", "*.pdf")])
        if p:
            self.split_file.set(p)

    def use_last_export(self) -> None:
        last = getattr(self.app.tab_code, "last_export", None)
        if last and Path(last).exists():
            self.split_file.set(str(last))
        else:
            messagebox.showinfo("Split", "Nu exista inca un export de cod.")

    def update_info(self) -> None:
        try:
            src = Path(self.split_file.get().strip().strip('"'))
            if not src.is_file():
                self.info.configure(text="")
                return
            self.info.configure(text=splitmerge.describe(src, float(self.split_size.get().replace(",", ".") or 100),
                                                         self.split_unit.get(), self.split_mode.get()))
        except Exception:
            self.info.configure(text="")

    def _progress(self, pct: float, label: str) -> None:
        self.app.call(self.prog.set, pct)
        self.app.call(self.status.set, label)

    # ── split ──
    def do_split(self) -> None:
        src = Path(self.split_file.get().strip().strip('"'))
        if not src.is_file():
            messagebox.showerror("Eroare", "Selecteaza un fisier sursa valid.")
            return
        try:
            size_val = float(self.split_size.get().replace(",", "."))
            assert size_val > 0
        except Exception:
            messagebox.showerror("Eroare", "Dimensiunea trebuie sa fie un numar pozitiv.")
            return
        out = Path(self.split_out.get().strip().strip('"'))
        if self.running:
            return
        self.running = True
        self.prog.set(0)

        def work():
            try:
                res = splitmerge.split_file(src, out, size_val, self.split_unit.get(), self.split_mode.get(),
                                            headers=self.headers.get(), progress=self._progress, log=self.tlog)
                self.last_dir = out
                self.app.call(self.status.set, f"Split finalizat: {len(res.parts)} parti in {out}")
                self.app.call(self.app.notify, "Split", f"{len(res.parts)} parti create")
                self.app.call(messagebox.showinfo, "Split Finalizat",
                              f"Fisierul a fost impartit in {len(res.parts)} parti.\nLocatie: {out}\nManifest: {res.manifest.name}")
                self.app.last_outputs = list(res.parts)
            except Exception as e:  # noqa: BLE001
                self.tlog(f"EROARE SPLIT: {e}", "error")
                self.app.call(messagebox.showerror, "Eroare Split", str(e))
            finally:
                self.running = False
        self.app.run_bg(work, name="split")

    # ── merge list ──
    def _refresh_lb(self) -> None:
        self.lb.delete(0, "end")
        for p in self.merge_files:
            self.lb.insert("end", f"{Path(p).name}  →  {p}")

    def add_merge(self) -> None:
        for p in filedialog.askopenfilenames(title="Selecteaza fisierele de combinat (acelasi tip)"):
            if p not in self.merge_files:
                self.merge_files.append(p)
        self._after_add()

    def add_parts_set(self) -> None:
        p = filedialog.askopenfilename(title="Alege ORICARE parte (…_part001of005…)")
        if not p:
            return
        m = splitmerge.PART_RE.match(Path(p).name)
        if not m:
            messagebox.showinfo("Merge", "Fisierul nu are formatul <nume>_partNNNofMMM<ext>.")
            return
        pattern = f"{m.group('stem')}_part*of{m.group('m')}{m.group('ext') or ''}"
        for f in Path(p).parent.glob(pattern):
            if str(f) not in self.merge_files:
                self.merge_files.append(str(f))
        self.sort_parts()
        self._after_add()

    def _after_add(self) -> None:
        self._refresh_lb()
        if self.merge_files and self.merge_name.get() in ("", "merged_output"):
            self.merge_name.set(splitmerge.suggested_output_name(self.merge_files))

    def remove_merge(self) -> None:
        sel = self.lb.curselection()
        if sel:
            self.merge_files.pop(sel[0])
            self._refresh_lb()

    def move(self, d: int) -> None:
        sel = self.lb.curselection()
        if not sel:
            return
        i, j = sel[0], sel[0] + d
        if 0 <= j < len(self.merge_files):
            self.merge_files[i], self.merge_files[j] = self.merge_files[j], self.merge_files[i]
            self._refresh_lb()
            self.lb.selection_set(j)

    def sort_parts(self) -> None:
        self.merge_files[:] = splitmerge.sort_parts(self.merge_files)
        self._refresh_lb()

    def clear_merge(self) -> None:
        self.merge_files.clear()
        self._refresh_lb()

    def do_merge(self) -> None:
        if not self.merge_files:
            messagebox.showerror("Eroare", "Adauga cel putin un fisier pentru merge.")
            return
        out_dir = Path(self.merge_out.get().strip().strip('"'))
        name = self.merge_name.get().strip() or "merged_output"
        ext = Path(self.merge_files[0]).suffix
        out_path = out_dir / (name if name.endswith(ext) and ext else f"{name}{ext}")
        if self.running:
            return
        self.running = True
        self.prog.set(0)
        files = list(self.merge_files)

        def work():
            try:
                res = splitmerge.merge_files(files, out_path, progress=self._progress, log=self.tlog)
                self.last_dir = out_path.parent
                extra = ""
                if res.missing:
                    extra += f"\n⚠️ Lipsesc partile: {res.missing}"
                if res.verified is True:
                    extra += "\n✅ SHA-256 identic cu originalul"
                elif res.verified is False:
                    extra += "\n❌ SHA-256 diferit de original"
                self.app.call(self.status.set, f"Merge finalizat: {out_path.name} ({res.size / 1024 ** 2:.2f} MB)")
                self.app.call(messagebox.showinfo, "Merge Finalizat",
                              f"Fisierele au fost combinate.\nRezultat: {out_path}\nDimensiune: {res.size / 1024 ** 2:.2f} MB{extra}")
                self.app.last_outputs = [out_path]
            except Exception as e:  # noqa: BLE001
                self.tlog(f"EROARE MERGE: {e}", "error")
                self.app.call(messagebox.showerror, "Eroare Merge", str(e))
            finally:
                self.running = False
        self.app.run_bg(work, name="merge")


class OneNoteTab:
    def __init__(self, app, frame):
        self.app, self.ui, self.T = app, app.ui, app.T
        self.files: List[str] = []
        self.out_dir = tk.StringVar(value=str(default_desktop() / "NexusX_OneNote"))
        self.o_text = tk.BooleanVar(value=True)
        self.o_imgs = tk.BooleanVar(value=True)
        self.o_att = tk.BooleanVar(value=True)
        self.o_md = tk.BooleanVar(value=True)
        self.o_open = tk.BooleanVar(value=True)
        self.prog = tk.DoubleVar(value=0)
        self.running = False
        self.results: List[onenote.PackageResult] = []
        self._build(frame)

    def _build(self, frame) -> None:
        ui, T = self.ui, self.T
        top = make_scrollable(frame, T)
        inf = ui.lframe(top, "📓 OneNote Extractor — .onepkg / .one / .onetoc2", fg=T["PURPLE"])
        inf.pack(fill="x", padx=12, pady=(10, 4))
        ui.label(inf, "Extrage continut din pachete .onepkg (Cabinet Microsoft) sau direct din sectiuni .one: "
                      "text (UTF-16 + UTF-8), imagini, atasamente, cuprins .onetoc2.",
                 fg=T["TEXT2"], font=("Segoe UI", 9, "italic")).pack(padx=12, pady=6, anchor="w")
        fl = ui.lframe(top, "Fisiere de extras")
        fl.pack(fill="x", padx=12, pady=(0, 4))
        lf = tk.Frame(fl, bg=T["BG2"])
        lf.pack(fill="x", padx=8, pady=6)
        sb = ttk.Scrollbar(lf, orient="vertical")
        self.lb = tk.Listbox(lf, bg=T["BG3"], fg=T["TEXT1"], selectbackground=T["ACCENT"], font=("Segoe UI", 9),
                             height=6, selectmode="extended", relief="flat", bd=0, yscrollcommand=sb.set)
        sb.config(command=self.lb.yview)
        sb.pack(side="right", fill="y")
        self.lb.pack(fill="x", expand=True)
        br = tk.Frame(fl, bg=T["BG2"])
        br.pack(fill="x", padx=8, pady=(0, 8))
        ui.btn(br, "📂 Adauga .onepkg / .one", self.add_files, fg=T["ACCENT"]).pack(side="left", padx=4)
        ui.btn(br, "📁 Adauga folder", self.add_folder, fg=T["TEAL"]).pack(side="left", padx=4)
        ui.btn(br, "❌ Sterge selectate", self.remove, fg=T["RED"]).pack(side="left", padx=4)
        ui.btn(br, "🗑 Goleste lista", self.clear, fg=T["TEXT3"]).pack(side="left", padx=4)
        of = ui.lframe(top, "Folder output")
        of.pack(fill="x", padx=12, pady=(0, 4))
        of.columnconfigure(1, weight=1)
        ui.label(of, "Destinatie:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ui.entry(of, self.out_dir, width=64).grid(row=0, column=1, sticky="ew", padx=4, pady=6)
        ui.btn(of, "📂 Browse", lambda: self.out_dir.set(filedialog.askdirectory() or self.out_dir.get()), fg=T["ACCENT"]).grid(row=0, column=2, padx=6)
        op = ui.lframe(top, "Optiuni extractie")
        op.pack(fill="x", padx=12, pady=(0, 4))
        orow = tk.Frame(op, bg=T["BG2"])
        orow.pack(fill="x", padx=8, pady=8)
        for var, lbl, tip in ((self.o_text, "Extrage text (.one → .txt)", "Text UTF-16 + UTF-8 detectabil, fara zgomot"),
                              (self.o_imgs, "Extrage imagini", "Imaginile din pachet + cele lipite in notite (PNG/JPEG/GIF)"),
                              (self.o_att, "Extrage atasamente", "Fisierele atasate (PDF, Office …) in _attachments/"),
                              (self.o_md, "Markdown combinat", "Un singur .md cu textul tuturor sectiunilor"),
                              (self.o_open, "Deschide folderul dupa extractie", "")):
            ui.chk(orow, lbl, var, tip).pack(side="left", padx=10)
        nf = ui.lframe(top, "ℹ Nota tehnica .onepkg")
        nf.pack(fill="x", padx=12, pady=(0, 4))
        ui.label(nf, "Un .onepkg este un Cabinet Microsoft (.cab, semnatura MSCF) cu sectiuni .one, cuprins .onetoc2, imagini si atasamente.\n"
                     "Ordinea incercarilor: cititor CAB intern (fara programe externe) → ZIP → cabarchive → expand.exe → 7-Zip.\n"
                     "Daca pachetul foloseste compresie LZX si nu ai 7-Zip: redenumeste .onepkg in .cab si deschide-l cu 7-Zip / WinRAR.",
                 fg=T["TEXT3"], font=("Segoe UI", 8, "italic"), justify="left").pack(padx=12, pady=6, anchor="w")
        af = ui.lframe(top, "Extractie")
        af.pack(fill="x", padx=12, pady=(0, 4))
        ar = tk.Frame(af, bg=T["BG2"])
        ar.pack(fill="x", padx=8, pady=8)
        ui.btn(ar, "📦 EXTRAGE", self.extract, fg=T["BG1"], bg=T["GREEN"]).pack(side="left", padx=8)
        ttk.Progressbar(ar, variable=self.prog, maximum=100, length=280).pack(side="left", padx=8)
        self.prog_lbl = ui.label(ar, "Gata.", fg=T["TEXT3"], font=("Segoe UI", 8))
        self.prog_lbl.pack(side="left", padx=8)
        ui.btn(ar, "📦 Text extras → Code Export", self.to_code_export, fg=T["PURPLE"]).pack(side="right", padx=4)
        lgf = ui.lframe(top, "Log extractie")
        lgf.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        fr, self.log_txt = ui.scrolled_text(lgf, height=10)
        fr.pack(fill="both", expand=True, padx=8, pady=6)
        b2 = tk.Frame(lgf, bg=T["BG2"])
        b2.pack(fill="x", padx=8, pady=(0, 6))
        ui.btn(b2, "📋 Copiaza log", self.copy_log, fg=T["TEAL"]).pack(side="left", padx=4)
        ui.btn(b2, "🗑 Goleste log", self.clear_log, fg=T["TEXT3"]).pack(side="left", padx=4)

    def log(self, msg: str, tag: str = "info") -> None:
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", f"[{datetime.datetime.now():%H:%M:%S}] {msg}\n", tag)
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")
        self.app.log(f"[ONENOTE] {msg}", "error" if tag == "error" else ("warn" if tag == "warn" else "info"))

    def clear_log(self) -> None:
        self.log_txt.configure(state="normal")
        self.log_txt.delete("1.0", "end")
        self.log_txt.configure(state="disabled")

    def copy_log(self) -> None:
        content = self.log_txt.get("1.0", "end").strip()
        if content:
            self.app.clipboard_clear()
            self.app.clipboard_append(content)
            self.app.set_status("✅ Log OneNote copiat.")

    def _refresh(self) -> None:
        self.lb.delete(0, "end")
        for p in self.files:
            self.lb.insert("end", p)

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Selecteaza fisiere .onepkg / .one",
                                            filetypes=[("OneNote", "*.onepkg *.one"), ("OneNote Package", "*.onepkg"),
                                                       ("OneNote Section", "*.one"), ("Toate fisierele", "*.*")])
        new = [p for p in paths if p not in self.files]
        self.files.extend(new)
        self._refresh()
        if new:
            self.log(f"Adaugate {len(new)} fisier(e).", "ok")

    def add_folder(self) -> None:
        d = filedialog.askdirectory(title="Folder cu .onepkg / .one")
        if not d:
            return
        new = [str(p) for p in sorted(Path(d).rglob("*")) if p.suffix.lower() in (".onepkg", ".one") and str(p) not in self.files]
        self.files.extend(new)
        self._refresh()
        self.log(f"Adaugate {len(new)} fisier(e) din {d}.", "ok")

    def remove(self) -> None:
        for i in reversed(list(self.lb.curselection())):
            del self.files[i]
        self._refresh()

    def clear(self) -> None:
        self.files.clear()
        self._refresh()

    def extract(self) -> None:
        if not self.files:
            messagebox.showinfo("Info", "Nu ai adaugat niciun fisier .onepkg / .one.")
            return
        if self.running:
            messagebox.showinfo("Info", "Extractie deja in curs…")
            return
        out = Path(self.out_dir.get().strip().strip('"'))
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Eroare", f"Nu pot crea folderul output:\n{e}")
            return
        opts = onenote.ExtractOptions(text=self.o_text.get(), images=self.o_imgs.get(), attachments=self.o_att.get(),
                                      combined_markdown=self.o_md.get(), open_after=False)
        files = list(self.files)
        open_after = self.o_open.get()
        self.running = True
        self.results = []

        def work():
            total = len(files)
            say = lambda m, t="info": self.app.call(self.log, m, t)  # noqa: E731
            say("═" * 50, "title")
            say(f" EXTRACTIE START — {total} fisier(e)", "title")
            for i, f in enumerate(files):
                src = Path(f)
                self.app.call(self.prog.set, i / total * 100)
                self.app.call(self.prog_lbl.configure, text=f"Procesez {src.name}…")
                say(f"[{i + 1}/{total}] {src.name}", "title")
                try:
                    self.results.append(onenote.process(src, out, opts, say))
                except Exception as e:  # noqa: BLE001
                    say(f"   ❌ {e}", "error")
            ok = sum(1 for r in self.results if r.ok)
            self.app.call(self.prog.set, 100)
            self.app.call(self.prog_lbl.configure, text=f"Gata: {ok}/{total} extrase.")
            say(f"══ EXTRACTIE FINALIZATA: {ok}/{total} ══", "title")
            self.app.call(self.app.notify, "OneNote", f"{ok}/{total} pachete extrase")
            if open_after and ok:
                self.app.call(open_path, out if ok > 1 else self.results[0].out_dir)
            self.running = False
        self.app.run_bg(work, name="onenote")

    def to_code_export(self) -> None:
        """Load the extracted text folder in Code Export (export/split/e-mail it like code)."""
        good = [r for r in self.results if r.ok]
        if not good:
            messagebox.showinfo("OneNote", "Extrage mai intai un pachet.")
            return
        target = good[0].out_dir if len(good) == 1 else good[0].out_dir.parent
        self.app.tab_code.folder.set(str(target))
        self.app.tab_code.out_name.set(f"OneNote_{target.name}")
        self.app.select_tab("code")
        self.app.tab_code.do_scan()
