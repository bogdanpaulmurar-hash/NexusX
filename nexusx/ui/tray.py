# -*- coding: utf-8 -*-
"""
Taskbar + system-tray integration.

Taskbar: sets a Windows AppUserModelID *before* the window exists so Windows groups the
window under NexusX with its own icon (instead of the generic Python icon), and applies
the .ico (iconbitmap) + PNG (iconphoto) to every window.

Tray: pystray icon with menu (Show/Hide, quick actions, notifications, Exit) running in
its own thread; all callbacks are marshalled back to the Tk thread.
"""
from __future__ import annotations

import os
import sys
import threading
import tkinter as tk
from typing import Callable, Dict, Optional

from .. import APP_ID, APP_NAME
from ..paths import ICON_ICO, ICON_PNG


def set_app_user_model_id() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def set_dpi_awareness() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def apply_window_icon(win: tk.Misc) -> Optional[tk.PhotoImage]:
    """Apply the NexusX icon to a Tk/Toplevel. Returns the PhotoImage (keep a reference!)."""
    photo = None
    try:
        if os.name == "nt" and ICON_ICO.exists():
            win.iconbitmap(default=str(ICON_ICO))  # type: ignore[call-arg]
    except Exception:
        pass
    try:
        if ICON_PNG.exists():
            photo = tk.PhotoImage(file=str(ICON_PNG))
            win.iconphoto(True, photo)  # type: ignore[attr-defined]
    except Exception:
        photo = None
    return photo


def tray_available() -> bool:
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


class TrayController:
    def __init__(self, root: tk.Tk, actions: Dict[str, Callable[[], None]],
                 on_show: Callable[[], None], on_hide: Callable[[], None], on_exit: Callable[[], None],
                 dispatch: Callable[[Callable[[], None]], None]):
        self.root = root
        self.actions = actions
        self.on_show, self.on_hide, self.on_exit = on_show, on_hide, on_exit
        self.dispatch = dispatch
        self.icon = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        if not tray_available():
            return False
        import pystray
        from PIL import Image

        try:
            img = Image.open(ICON_PNG) if ICON_PNG.exists() else Image.new("RGBA", (64, 64), (0, 100, 135, 255))
        except Exception:
            img = Image.new("RGBA", (64, 64), (0, 100, 135, 255))

        def item(text, key):
            return pystray.MenuItem(text, lambda _i, _it: self.dispatch(self.actions[key]))

        items = [pystray.MenuItem(f"Arata {APP_NAME}", lambda _i, _it: self.dispatch(self.on_show), default=True),
                 pystray.MenuItem("Ascunde in tray", lambda _i, _it: self.dispatch(self.on_hide)),
                 pystray.Menu.SEPARATOR]
        labels = {"scan_export": "📦 Scan + Export folder curent", "run_manager": "🚀 Ruleaza Export Manager",
                  "check_links": "🔗 Verifica linkurile (HTTP)", "linkmap": "🕸 Genereaza Link Map",
                  "email": "✉ Trimite email raport", "open_reports": "📂 Deschide folder rapoarte"}
        for key, text in labels.items():
            if key in self.actions:
                items.append(item(text, key))
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Iesire", lambda _i, _it: self.dispatch(self.on_exit))]
        self.icon = pystray.Icon(APP_NAME, img, APP_NAME, pystray.Menu(*items))
        self._thread = threading.Thread(target=self.icon.run, daemon=True)
        self._thread.start()
        return True

    def notify(self, title: str, message: str) -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message[:250], title[:60])
            except Exception:
                pass

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)
