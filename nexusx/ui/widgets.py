# -*- coding: utf-8 -*-
"""Reusable themed widget helpers (UCeX helper methods, shared by all tabs)."""
from __future__ import annotations

import os
import platform
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Dict, Optional, Sequence, Tuple


def open_path(path) -> None:
    """Open a file or folder in the OS (UCeX open_folder, generalised)."""
    p = Path(str(path))
    if not p.exists():
        messagebox.showwarning("Cale inexistenta", f"Nu exista:\n{p}")
        return
    try:
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception as e:  # noqa: BLE001
        messagebox.showerror("Eroare", f"Nu pot deschide:\n{e}")


def reveal(path) -> None:
    p = Path(str(path))
    if os.name == "nt" and p.is_file():
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        open_path(p if p.is_dir() else p.parent)


class UI:
    """Mixin-like helper bound to a theme dict."""

    def __init__(self, T: Dict[str, str]):
        self.T = T

    def label(self, parent, text="", fg=None, font=("Segoe UI", 9), **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=fg or self.T["TEXT2"], font=font, **kw)

    def entry(self, parent, var, width=40, **kw) -> tk.Entry:
        T = self.T
        return tk.Entry(parent, textvariable=var, width=width, bg=T["BG3"], fg=T["TEXT1"],
                        insertbackground=T["TEXT1"], relief="flat", font=("Segoe UI", 9), **kw)

    def btn(self, parent, text, cmd=None, fg=None, bg=None, bold=True, padx=12, pady=5, primary=False,
            danger=False, **kw) -> tk.Button:
        T = self.T
        if primary:
            bg, fg = T["ACCENT2"], "#ffffff"
        elif danger:
            bg, fg = "#b42318", "#ffffff"
        bg = bg or T["BG3"]
        fg = fg or T["TEXT1"]
        b = tk.Button(parent, text=text, bg=bg, fg=fg, activebackground=T["ACCENT"], activeforeground="#ffffff",
                      relief="flat", bd=0, cursor="hand2", font=("Segoe UI", 9, "bold" if bold else "normal"),
                      padx=padx, pady=pady, command=cmd, **kw)
        b.bind("<Enter>", lambda e: b.configure(bg=T["ACCENT"], fg="#ffffff") if str(b["state"]) != "disabled" else None)
        b.bind("<Leave>", lambda e: b.configure(bg=bg, fg=fg))
        return b

    def chk(self, parent, text, var, tip: str = "", command=None, fg=None) -> tk.Checkbutton:
        T = self.T
        cb = tk.Checkbutton(parent, text=text, variable=var, bg=parent.cget("bg"), fg=fg or T["TEXT1"],
                            selectcolor=T["BG3"], activebackground=parent.cget("bg"),
                            activeforeground=T["TEXT1"], font=("Segoe UI", 9), command=command)
        if tip:
            self.tooltip(cb, tip)
        return cb

    def radio(self, parent, text, var, value, command=None, bold=False) -> tk.Radiobutton:
        T = self.T
        return tk.Radiobutton(parent, text=text, variable=var, value=value, bg=parent.cget("bg"), fg=T["TEXT1"],
                              selectcolor=T["BG3"], activebackground=parent.cget("bg"), activeforeground=T["TEXT1"],
                              font=("Segoe UI", 9, "bold" if bold else "normal"), command=command)

    def lframe(self, parent, text, fg=None) -> tk.LabelFrame:
        T = self.T
        return tk.LabelFrame(parent, text=f" {text} ", bg=T["BG2"], fg=fg or T["ACCENT"],
                             font=("Segoe UI", 9, "bold"), relief="flat",
                             highlightbackground=T["SEP"], highlightthickness=1)

    def sep_v(self, parent) -> tk.Frame:
        return tk.Frame(parent, width=2, bg=self.T["SEP"])

    def scrolled_text(self, parent, height=12) -> Tuple[tk.Frame, tk.Text]:
        T = self.T
        frame = tk.Frame(parent, bg=T["BG2"])
        sb = ttk.Scrollbar(frame)
        sb.pack(side="right", fill="y")
        txt = tk.Text(frame, height=height, bg=T["BG1"], fg=T["TEXT1"], insertbackground=T["TEXT1"],
                      font=("Consolas", 9), relief="flat", state="disabled", yscrollcommand=sb.set,
                      wrap="none", padx=8, pady=6)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        for tag, color in (("title", "ACCENT"), ("info", "TEXT1"), ("ok", "GREEN"), ("warn", "YELLOW"),
                           ("error", "RED"), ("section", "PURPLE"), ("debug", "TEXT3")):
            txt.tag_config(tag, foreground=T[color])
        txt.tag_config("title", font=("Consolas", 9, "bold"))
        return frame, txt

    def tooltip(self, widget, text: str) -> None:
        state = {"tip": None}

        def show(e):
            if state["tip"]:
                return
            tip = tk.Toplevel(widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{e.x_root + 12}+{e.y_root + 8}")
            tk.Label(tip, text=text, bg="#2a2f3a", fg="#f1f4f8", font=("Segoe UI", 8), relief="solid", bd=1,
                     padx=6, pady=3, wraplength=360, justify="left").pack()
            state["tip"] = tip

        def hide(_e):
            if state["tip"]:
                state["tip"].destroy()
                state["tip"] = None

        widget.bind("<Enter>", show, add="+")
        widget.bind("<Leave>", hide, add="+")

    def tree(self, parent, columns: Sequence[Tuple[str, str, int, str]], height=12,
             selectmode="extended") -> ttk.Treeview:
        """columns: (id, heading, width, anchor). Adds scrollbars and click-to-sort headings."""
        frame = tk.Frame(parent, bg=self.T["BG2"])
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        tv = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode=selectmode)
        for cid, head, width, anchor in columns:
            tv.heading(cid, text=head, command=lambda c=cid: self._sort(tv, c, False))
            tv.column(cid, width=width, minwidth=40, anchor=anchor)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tv

    @staticmethod
    def _sort(tv: ttk.Treeview, col: str, reverse: bool) -> None:
        rows = [(tv.set(k, col), k) for k in tv.get_children("")]

        def key(v):
            s = v[0]
            try:
                return (0, float(str(s).replace(" KB", "").replace(",", ".")))
            except ValueError:
                return (1, str(s).lower())

        rows.sort(key=key, reverse=reverse)
        for i, (_v, k) in enumerate(rows):
            tv.move(k, "", i)
        tv.heading(col, command=lambda: UI._sort(tv, col, not reverse))


def make_scrollable(parent, T) -> tk.Frame:
    """Wrap a tab in canvas+scrollbar (UCeX _make_scrollable_tab) with wheel support everywhere."""
    canvas = tk.Canvas(parent, bg=T["BG2"], highlightthickness=0)
    vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=T["BG2"])
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

    def wheel(e):
        # do not steal the wheel from treeviews / text widgets
        w = e.widget
        if isinstance(w, (ttk.Treeview, tk.Text, tk.Listbox)):
            return
        delta = -1 if (getattr(e, "num", 0) == 4 or e.delta > 0) else 1
        canvas.yview_scroll(delta, "units")

    def bind_all_children(_e=None):
        def rec(w):
            if not isinstance(w, (ttk.Treeview, tk.Text, tk.Listbox)):
                w.bind("<MouseWheel>", wheel, add="+")
                w.bind("<Button-4>", wheel, add="+")
                w.bind("<Button-5>", wheel, add="+")
            for c in w.winfo_children():
                rec(c)
        rec(inner)

    canvas.bind("<MouseWheel>", wheel)
    parent.after(400, bind_all_children)
    inner.rebind_wheel = bind_all_children  # type: ignore[attr-defined]
    return inner


def ask_text(parent, title: str, prompt: str, show: str = "") -> Optional[str]:
    from tkinter import simpledialog
    return simpledialog.askstring(title, prompt, parent=parent, show=show or None)


Callback = Callable[..., None]
