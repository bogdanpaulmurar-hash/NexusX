# -*- coding: utf-8 -*-
"""Themes: Siemens Petrol (ULaE look, default) + Catppuccin Dark/Light (UCeX look)."""
from __future__ import annotations

from tkinter import ttk

THEMES = {
    "petrol": {
        "BG1": "#1c1f26", "BG2": "#22262f", "BG3": "#323745",
        "TEXT1": "#f1f4f8", "TEXT2": "#c9d3df", "TEXT3": "#8e9bb0",
        "ACCENT": "#00a3be", "ACCENT2": "#006487", "GREEN": "#4ade80", "RED": "#f87171",
        "YELLOW": "#fbbf24", "PURPLE": "#c4b5fd", "TEAL": "#2dd4bf", "PINK": "#f9a8d4",
        "SEP": "#3a4050", "ORANGE": "#fb923c", "ROW_ALT": "#262b35",
    },
    "dark": {
        "BG1": "#1e1e2e", "BG2": "#181825", "BG3": "#313244",
        "TEXT1": "#cdd6f4", "TEXT2": "#bac2de", "TEXT3": "#6c7086",
        "ACCENT": "#89b4fa", "ACCENT2": "#5b7ec9", "GREEN": "#a6e3a1", "RED": "#f38ba8",
        "YELLOW": "#f9e2af", "PURPLE": "#cba6f7", "TEAL": "#94e2d5", "PINK": "#f5c2e7",
        "SEP": "#45475a", "ORANGE": "#fab387", "ROW_ALT": "#1f1f30",
    },
    "light": {
        "BG1": "#eff1f5", "BG2": "#e6e9ef", "BG3": "#dce0e8",
        "TEXT1": "#4c4f69", "TEXT2": "#5c5f77", "TEXT3": "#8c8fa1",
        "ACCENT": "#1e66f5", "ACCENT2": "#006487", "GREEN": "#40a02b", "RED": "#d20f39",
        "YELLOW": "#df8e1d", "PURPLE": "#8839ef", "TEAL": "#179299", "PINK": "#ea76cb",
        "SEP": "#ccd0da", "ORANGE": "#fe640b", "ROW_ALT": "#eef0f4",
    },
}
THEME_LABELS = {"petrol": "🟦 Siemens Petrol", "dark": "🌙 Dark (Catppuccin)", "light": "☀️ Light (Catppuccin)"}

STATUS_TAG_COLORS = {  # foreground per status group for treeviews
    "ok": "GREEN", "broken": "RED", "auth": "ORANGE", "download": "TEAL", "warn": "YELLOW", "pending": "TEXT3",
}


def apply_styles(root, T) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background=T["BG2"], foreground=T["TEXT1"])
    style.configure("TNotebook", background=T["BG1"], borderwidth=0, tabmargins=[2, 5, 2, 0])
    style.configure("TNotebook.Tab", background=T["BG3"], foreground=T["TEXT2"], padding=[14, 7],
                    font=("Segoe UI", 9, "bold"))
    style.map("TNotebook.Tab", background=[("selected", T["ACCENT"])], foreground=[("selected", "#ffffff")])
    style.configure("TProgressbar", troughcolor=T["BG3"], background=T["ACCENT"], thickness=8)
    style.configure("Horizontal.TProgressbar", troughcolor=T["BG3"], background=T["ACCENT"])
    style.configure("Treeview", background=T["BG2"], foreground=T["TEXT1"], fieldbackground=T["BG2"],
                    rowheight=24, font=("Segoe UI", 9))
    style.configure("Treeview.Heading", background=T["BG3"], foreground=T["ACCENT"],
                    font=("Segoe UI", 9, "bold"), relief="flat")
    style.map("Treeview", background=[("selected", T["ACCENT2"])], foreground=[("selected", "#ffffff")])
    style.configure("TScrollbar", background=T["BG3"], troughcolor=T["BG2"], arrowcolor=T["TEXT3"])
    style.configure("TCombobox", fieldbackground=T["BG3"], background=T["BG3"], foreground=T["TEXT1"],
                    selectbackground=T["BG3"], selectforeground=T["TEXT1"])
    root.option_add("*TCombobox*Listbox.background", T["BG3"])
    root.option_add("*TCombobox*Listbox.foreground", T["TEXT1"])
