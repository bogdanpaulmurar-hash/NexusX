# -*- coding: utf-8 -*-
"""Entry point:  python -m nexusx  [--minimized]"""
from __future__ import annotations

import sys


def main() -> int:
    from .logbus import setup_logging
    setup_logging()
    try:
        from .ui.app import NexusXApp
    except ModuleNotFoundError as e:  # tkinter missing (e.g. minimal Python)
        print(f"NexusX needs Tkinter: {e}")
        return 1
    app = NexusXApp(start_minimized="--minimized" in sys.argv)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
