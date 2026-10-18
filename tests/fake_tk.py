# -*- coding: utf-8 -*-
"""
Minimal headless stand-in for tkinter so the whole GUI construction code can be
exercised in CI / containers without a display or Tk installed.
It does not emulate rendering — it catches NameError/AttributeError/logic bugs
in our UI code paths.
"""
import sys
import types


class W:
    def __init__(self, *a, **k):
        self._cfg = dict(k)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: W()

    def __getitem__(self, k):
        return self._cfg.get(k, "normal")

    def __setitem__(self, k, v):
        self._cfg[k] = v

    def cget(self, k, *a):
        return self._cfg.get(k, "#000000")

    def configure(self, *a, **k):
        self._cfg.update(k)

    config = configure

    def winfo_children(self):
        return []

    def winfo_viewable(self):
        return True

    def subsample(self, *a):
        return W()

    def __bool__(self):
        return True


class Tk(W):
    def __init__(self, *a, **k):
        super().__init__()
        self._after = []

    def after(self, ms, fn=None, *args):
        if fn:
            self._after.append((fn, args))
        return "after#"

    def run_after(self, rounds=3):
        for _ in range(rounds):
            jobs, self._after = self._after, []
            for fn, args in jobs:
                fn(*args)

    def state(self, *a):
        return "normal"

    def geometry(self, *a):
        return "1480x900+0+0"


class Var:
    _default = ""

    def __init__(self, master=None, value=None, name=None):
        self._v = self._default if value is None else value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class StringVar(Var):
    _default = ""


class IntVar(Var):
    _default = 0

    def get(self):
        return int(self._v)


class DoubleVar(Var):
    _default = 0.0


class BooleanVar(Var):
    _default = False

    def get(self):
        return bool(self._v)


class Treeview(W):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._rows = {}
        self._order = []
        self._sel = []
        self._n = 0

    def insert(self, parent, index, iid=None, values=(), tags=(), **k):
        self._n += 1
        iid = iid or f"I{self._n:05d}"
        self._rows[iid] = {"values": tuple(values), "tags": tuple(tags)}
        self._order.append(iid)
        return iid

    def get_children(self, item=""):
        return tuple(self._order)

    def delete(self, *iids):
        for i in iids:
            self._rows.pop(i, None)
            if i in self._order:
                self._order.remove(i)

    def item(self, iid, option=None, **k):
        if k:
            self._rows[iid].update(k)
            return None
        if option:
            return self._rows[iid][option]
        return self._rows[iid]

    def exists(self, iid):
        return iid in self._rows

    def selection(self):
        return tuple(self._sel)

    def selection_set(self, items):
        self._sel = list(items) if isinstance(items, (list, tuple)) else [items]

    def index(self, iid):
        return self._order.index(iid)

    def set(self, iid, col):
        return ""

    def move(self, *a):
        pass

    def identify_row(self, y):
        return self._order[0] if self._order else ""


class Notebook(W):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._tabs = []

    def add(self, child, **k):
        if child not in self._tabs:
            self._tabs.append(child)

    def select(self, tab=None):
        return "tab0" if tab is None else None

    def index(self, tab):
        return 0


def install():
    tk = types.ModuleType("tkinter")
    for name in ("Frame", "Label", "Button", "Entry", "Checkbutton", "Radiobutton", "LabelFrame", "Canvas", "Text",
                 "Toplevel", "Menu", "Spinbox", "PanedWindow", "Listbox", "PhotoImage", "Scrollbar"):
        setattr(tk, name, type(name, (W,), {}))
    tk.Tk, tk.Misc = Tk, W
    tk.StringVar, tk.IntVar, tk.DoubleVar, tk.BooleanVar = StringVar, IntVar, DoubleVar, BooleanVar
    tk.TclError = Exception
    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Progressbar", "Scrollbar", "Combobox", "Style", "Frame", "Label"):
        setattr(ttk, name, type(name, (W,), {}))
    ttk.Treeview, ttk.Notebook = Treeview, Notebook
    mb = types.ModuleType("tkinter.messagebox")
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(mb, name, lambda *a, **k: "ok")
    mb.askyesno = lambda *a, **k: False
    fd = types.ModuleType("tkinter.filedialog")
    for name in ("askdirectory", "askopenfilename", "asksaveasfilename"):
        setattr(fd, name, lambda *a, **k: "")
    fd.askopenfilenames = lambda *a, **k: ()
    sd = types.ModuleType("tkinter.simpledialog")
    sd.askstring = lambda *a, **k: None
    tk.ttk, tk.messagebox, tk.filedialog, tk.simpledialog = ttk, mb, fd, sd
    sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.messagebox": mb,
                        "tkinter.filedialog": fd, "tkinter.simpledialog": sd})
