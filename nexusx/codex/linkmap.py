# -*- coding: utf-8 -*-
"""
Link Map — NEW in NexusX.

Statically analyses one or many code folders (e.g. all Export Manager pairs) and
extracts every "connection" a tool has to the outside world or to the user's
other tools:

  url         web addresses used in code (SharePoint, Wiki, APIs, portals)
  import      Python / JS / TS / C# / Java imports (classified stdlib / 3rd-party / own / other project)
  project_ref .csproj ProjectReference / PackageReference, requirements.txt, package.json deps
  path        absolute Windows paths, UNC shares, OneDrive folders
  db          connection strings, sqlite files, JDBC / Mongo / Postgres URIs (credentials masked)
  automation  Selenium / Playwright targets, COM automation (Outlook, Excel, SAP GUI),
              Process.Start / subprocess, Google Apps Script services
  auth        SSO / OAuth / MSAL / ADFS / tenant / client-id usage
  env         environment variables read by the code
  endpoint    HTTP routes exposed or called (/api/…, @app.route, [HttpGet])

It then resolves project → project dependencies (shared paths, imports of another
project's modules, ProjectReferences) and resources shared by several tools.
Output: Markdown (with Mermaid graph), JSON, CSV and an interactive HTML page.
"""
from __future__ import annotations

import csv
import datetime
import html
import io
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from .. import APP_NAME, APP_VERSION
from .constants import DEFAULT_EXCLUDED, is_code_file
from .redact import redact
from .scanner import ScanOptions, is_binary, read_text, scan_folder

KINDS = ("url", "import", "project_ref", "path", "db", "automation", "auth", "env", "endpoint")

_STDLIB: Set[str] = set(getattr(sys, "stdlib_module_names", ())) | {
    "os", "sys", "re", "json", "time", "datetime", "pathlib", "typing", "logging", "threading",
    "subprocess", "tkinter", "collections", "itertools", "functools", "dataclasses", "abc",
}
_NAMESPACE_HOSTS = ("www.w3.org", "schemas.openxmlformats.org", "schemas.microsoft.com", "purl.org",
                    "xmlns.com", "json-schema.org", "schemas.android.com", "ns.adobe.com",
                    "www.apache.org/licenses", "opensource.org", "example.com", "localhost.example")

URL_RE = re.compile(r"""(?i)\b(?:https?|wss?|ftp)://[^\s"'<>`\\)\]}]+""")
WIN_PATH_RE = re.compile(r"""(?<![\w/])([A-Za-z]:[\\/](?:[^\\/:*?"'<>|\r\n]+[\\/])*[^\\/:*?"'<>|\r\n]*)""")
UNC_RE = re.compile(r"""(\\\\[A-Za-z0-9_.\-$]+\\[^\s"'<>|*?]+)""")

_IMPORT_PATTERNS: List[Tuple[Set[str], "re.Pattern[str]"]] = [
    ({".py", ".pyw", ".pyi"}, re.compile(r"^\s*from\s+([\w.]+)\s+import\b")),
    ({".py", ".pyw", ".pyi"}, re.compile(r"^\s*import\s+([\w.]+(?:\s*,\s*[\w.]+)*)")),
    ({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"},
     re.compile(r"""(?:^\s*import\s[^'"]*?from\s*|^\s*import\s*|require\(\s*|import\(\s*)['"]([^'"]+)['"]""")),
    ({".cs"}, re.compile(r"^\s*using\s+(?:static\s+)?([\w.]+)\s*;")),
    ({".java", ".kt", ".scala", ".groovy"}, re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)")),
    ({".vb"}, re.compile(r"^\s*Imports\s+([\w.]+)", re.I)),
]

_DB_RE = re.compile(
    r"""(?ix)
    ( (?:server|data\ source|initial\ catalog|database)\s*=\s*[^;"'\r\n]+;[^"'\r\n]* )
    | ( jdbc:[a-z0-9]+:[^\s"']+ )
    | ( (?:mongodb(?:\+srv)?|postgres(?:ql)?|mysql|mariadb|redis|mssql|sqlserver|oracle)://[^\s"']+ )
    | ( sqlite3\.connect\(\s*[^)]+\) )
    | ( ["'][^"'\r\n]+\.(?:db|sqlite3?|accdb|mdb)["'] )
    """)

_AUTOMATION: List[Tuple[str, "re.Pattern[str]"]] = [
    ("selenium", re.compile(r"""driver\.get\(\s*([^)]+)\)""")),
    ("playwright", re.compile(r"""\.goto\(\s*([^,)]+)""")),
    ("browser", re.compile(r"""webbrowser\.open(?:_new_tab)?\(\s*([^)]+)\)""")),
    ("com", re.compile(r"""(?:Dispatch(?:Ex)?|GetObject|GetActiveObject|CreateObject)\(\s*["']([\w. ]+)["']""", re.I)),
    ("process", re.compile(r"""(?:subprocess\.(?:run|Popen|call|check_output|check_call)|os\.startfile|os\.system|Process\.Start)\(\s*(.{0,160})""")),
    ("gui_automation", re.compile(r"""\b(pyautogui|pywinauto|uiautomation|FlaUI|AutoIt|keyboard\.send|SendKeys)\b""")),
    ("apps_script", re.compile(r"""\b((?:SpreadsheetApp|DriveApp|DocumentApp|GmailApp|UrlFetchApp|CalendarApp|FormApp)\.\w+\(\s*[^)]{0,120}\))""")),
    ("http_client", re.compile(r"""\b((?:requests|httpx|aiohttp|urllib\.request|HttpClient|axios|fetch)\b[.\w]*\(\s*[^)]{0,140})""")),
    ("sap", re.compile(r"""\b(SAPGUI|GuiApplication|ScriptingEngine|SAP\.Functions|pyrfc|RfcConnection)\b""")),
]
_AUTH_RE = re.compile(r"""(?i)\b(login\.microsoftonline\.com[^\s"']*|adfs[\w./\-]*|msal\b|PublicClientApplication|ConfidentialClientApplication|
                         oauth2?\b|saml\b|openid\b|ntlm\b|kerberos\b|tenant[_\- ]?id|client[_\- ]?id|azure\.identity|DefaultAzureCredential|
                         Negotiate|IntegratedWindowsAuthentication|UseDefaultCredentials)""", re.X)
_ENV_RE = re.compile(r"""(?:os\.environ(?:\.get)?\(?\[?\s*['"]([A-Z0-9_]+)['"]|os\.getenv\(\s*['"]([A-Z0-9_]+)['"]|
                         Environment\.GetEnvironmentVariable\(\s*"([A-Za-z0-9_]+)"|process\.env\.([A-Za-z0-9_]+)|%([A-Z0-9_]+)%)""", re.X)
_ENDPOINT_RE = re.compile(r"""(?:@(?:app|router|bp|blueprint|api)\.(?:route|get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]|
                              \[(?:Http(?:Get|Post|Put|Delete|Patch)|Route)\(\s*"([^"]*)"\)\]|
                              ['"](/api/[A-Za-z0-9_\-/{}.:]+)['"])""", re.X)
_PROJ_REF_RE = re.compile(r"""<(ProjectReference|PackageReference|Reference|COMReference)\s+Include\s*=\s*"([^"]+)"(?:[^>]*Version\s*=\s*"([^"]+)")?""", re.I)


@dataclass
class Edge:
    project: str
    file: str
    line: int
    kind: str
    target: str
    detail: str = ""
    resolved_project: str = ""   # another project this edge points into
    scope: str = ""              # import scope: stdlib | third-party | own | cross

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ProjectInfo:
    name: str
    root: Path
    modules: Set[str] = field(default_factory=set)
    namespaces: Set[str] = field(default_factory=set)
    package_names: Set[str] = field(default_factory=set)
    files: int = 0


@dataclass
class LinkMapResult:
    projects: List[ProjectInfo] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    generated: str = field(default_factory=lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ── derived views ──
    def project_links(self) -> Dict[Tuple[str, str], List[Edge]]:
        out: Dict[Tuple[str, str], List[Edge]] = defaultdict(list)
        for e in self.edges:
            if e.resolved_project and e.resolved_project != e.project:
                out[(e.project, e.resolved_project)].append(e)
        return out

    def shared_resources(self) -> List[Tuple[str, str, List[str]]]:
        by: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
        for e in self.edges:
            if e.kind in ("url", "path", "db", "automation", "env", "endpoint"):
                key = _normalise_target(e.kind, e.target)
                if key:
                    by[(e.kind, key)].add(e.project)
        rows = [(k, t, sorted(p)) for (k, t), p in by.items() if len(p) > 1]
        rows.sort(key=lambda r: (-len(r[2]), r[0], r[1]))
        return rows

    def unique_urls(self) -> List[Tuple[str, Edge]]:
        seen: Dict[str, Edge] = {}
        for e in self.edges:
            if e.kind == "url" and e.target not in seen:
                seen[e.target] = e
        return list(seen.items())


def _normalise_target(kind: str, target: str) -> str:
    t = target.strip().strip("'\"").rstrip("/")
    if kind == "url":
        return t.split("#")[0].lower()
    if kind == "path":
        return t.replace("/", "\\").lower()
    return t.lower()


def _clean_url(u: str) -> str:
    u = u.rstrip(".,;:!?'\"")
    while u.endswith(")") and u.count("(") < u.count(")"):
        u = u[:-1]
    # strip template placeholders tails like {0}, ${x}
    return u


def _is_namespace_url(u: str) -> bool:
    low = u.lower()
    return any(h in low for h in _NAMESPACE_HOSTS)


def _project_index(name: str, root: Path, files: List[Path]) -> ProjectInfo:
    info = ProjectInfo(name=name, root=root, files=len(files))
    for fp in files:
        try:
            rel = fp.relative_to(root)
        except ValueError:
            continue
        suffix = fp.suffix.lower()
        if suffix == ".py":
            top = rel.parts[0]
            info.modules.add(Path(top).stem if len(rel.parts) == 1 else top)
            if fp.name == "__init__.py":
                info.modules.add(".".join(rel.parts[:-1]))
            info.modules.add(fp.stem)
        elif suffix == ".cs":
            try:
                head = read_text(fp)[:20000]
                for m in re.finditer(r"^\s*namespace\s+([\w.]+)", head, re.M):
                    info.namespaces.add(m.group(1))
            except Exception:
                pass
        elif suffix in (".csproj", ".vbproj", ".fsproj"):
            info.package_names.add(fp.stem.lower())
        elif fp.name.lower() == "package.json":
            try:
                pj = json.loads(read_text(fp))
                if isinstance(pj.get("name"), str):
                    info.package_names.add(pj["name"].lower())
            except Exception:
                pass
    info.modules.discard("")
    info.modules -= {"__init__", "main", "app", "setup", "test", "tests", "utils", "config", "models", "__main__"}
    return info


def _scan_file(project: str, root: Path, fp: Path, redact_secrets: bool) -> List[Edge]:
    edges: List[Edge] = []
    try:
        rel = str(fp.relative_to(root))
    except ValueError:
        rel = str(fp)
    try:
        text = read_text(fp)
    except Exception:
        return edges
    suffix = fp.suffix.lower()
    name = fp.name.lower()

    def add(line_no, kind, target, detail=""):
        target = target.strip()
        if not target:
            return
        if redact_secrets and kind in ("db", "url", "auth", "automation"):
            target, _ = redact(target)
            detail, _ = redact(detail)
        edges.append(Edge(project, rel, line_no, kind, target[:400], detail[:300]))

    # structured dependency files
    if name == "requirements.txt" or name.startswith("requirements") and suffix == ".txt":
        for i, line in enumerate(text.splitlines(), 1):
            s = line.split("#")[0].strip()
            if s and not s.startswith("-"):
                pkg = re.split(r"[<>=!~\[; ]", s, 1)[0]
                add(i, "project_ref", pkg, f"pip: {s}")
    if name == "package.json":
        try:
            pj = json.loads(text)
            for sec in ("dependencies", "devDependencies", "peerDependencies"):
                for k, v in (pj.get(sec) or {}).items():
                    add(0, "project_ref", k, f"npm {sec}: {v}")
        except Exception:
            pass

    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 3000:  # minified / data blobs
            line = line[:3000]
        stripped = line.strip()
        if not stripped:
            continue
        for u in URL_RE.findall(line):
            u = _clean_url(u)
            if len(u) > 10 and not _is_namespace_url(u):
                add(i, "url", u, stripped[:200])
        for exts, pat in _IMPORT_PATTERNS:
            if suffix in exts:
                m = pat.search(line)
                if m:
                    for mod in re.split(r"\s*,\s*", m.group(1)):
                        mod = mod.split(" as ")[0].strip()
                        if mod:
                            add(i, "import", mod, stripped[:200])
        for m in _PROJ_REF_RE.finditer(line):
            add(i, "project_ref", m.group(2), f"{m.group(1)}" + (f" v{m.group(3)}" if m.group(3) else ""))
        for m in WIN_PATH_RE.finditer(line):
            p = m.group(1).rstrip(" .,;)")
            if len(p) > 4 and not p.lower().startswith(("c:\\windows\\system32", "c:/windows/system32")):
                add(i, "path", p, stripped[:200])
        for m in UNC_RE.finditer(line):
            add(i, "path", m.group(1).rstrip(" .,;)"), stripped[:200])
        for m in _DB_RE.finditer(line):
            add(i, "db", next(g for g in m.groups() if g), stripped[:200])
        for label, pat in _AUTOMATION:
            for m in pat.finditer(line):
                add(i, "automation", m.group(1).strip(), label)
        for m in _AUTH_RE.finditer(line):
            add(i, "auth", m.group(1), stripped[:200])
        for m in _ENV_RE.finditer(line):
            var = next((g for g in m.groups() if g), "")
            if var and not (suffix not in (".bat", ".cmd") and m.group(5)):
                add(i, "env", var, stripped[:200])
        for m in _ENDPOINT_RE.finditer(line):
            ep = next((g for g in m.groups() if g), "")
            add(i, "endpoint", ep, stripped[:200])
    return edges


def analyse(projects: Iterable[Tuple[str, Path]], scan_opts: Optional[ScanOptions] = None,
            redact_secrets: bool = True,
            progress: Optional[Callable[[str], None]] = None,
            stop: Optional[Callable[[], bool]] = None) -> LinkMapResult:
    """Analyse (name, root) folders and resolve cross-project links."""
    opts = scan_opts or ScanOptions.full()
    result = LinkMapResult()
    file_lists: Dict[str, Tuple[Path, List[Path]]] = {}
    for name, root in projects:
        root = Path(root)
        if not root.exists():
            if progress:
                progress(f"⚠️ [{name}] sursa lipseste: {root}")
            continue
        if progress:
            progress(f"🔍 [{name}] scanare {root}")
        files = [f for f in scan_folder(root, opts, stop=stop) if is_code_file(f) and not is_binary(f)]
        file_lists[name] = (root, files)
        result.projects.append(_project_index(name, root, files))

    for name, (root, files) in file_lists.items():
        if stop and stop():
            break
        n_before = len(result.edges)
        for fp in files:
            if stop and stop():
                break
            result.edges.extend(_scan_file(name, root, fp, redact_secrets))
        if progress:
            progress(f"✅ [{name}] {len(files)} fisiere → {len(result.edges) - n_before} legaturi")

    _resolve(result)
    return result


def _resolve(result: LinkMapResult) -> None:
    roots = sorted(((p.name, str(p.root.resolve()).lower().rstrip("\\/")) for p in result.projects),
                   key=lambda x: -len(x[1]))
    mod_owner: Dict[str, str] = {}
    for p in result.projects:
        for m in p.modules:
            mod_owner.setdefault(m.lower(), p.name)
        for ns in p.namespaces:
            mod_owner.setdefault(ns.lower(), p.name)
        for pk in p.package_names:
            mod_owner.setdefault(pk.lower(), p.name)
    own_mods = {p.name: {m.lower() for m in p.modules | p.namespaces} for p in result.projects}

    def owner_of_path(path: str) -> str:
        try:
            norm = str(PureWindowsPath(path)).lower().rstrip("\\") if re.match(r"^[A-Za-z]:|^\\\\", path) \
                else str(Path(path).resolve()).lower()
        except Exception:
            return ""
        for name, root in roots:
            r = root.replace("/", "\\")
            n = norm.replace("/", "\\")
            if n == r or n.startswith(r + "\\"):
                return name
        return ""

    for e in result.edges:
        if e.kind == "path":
            e.resolved_project = owner_of_path(e.target)
        elif e.kind == "import":
            mod = e.target.lstrip(".").lower()
            top = mod.split(".")[0] if not e.target.startswith((".", "/")) else ""
            if e.target.startswith("."):
                e.scope = "own"
            elif mod in own_mods.get(e.project, set()) or top in own_mods.get(e.project, set()):
                e.scope = "own"
            elif top in _STDLIB or mod.startswith(("system", "microsoft.", "java.", "javax.", "node:")):
                e.scope = "stdlib"
            else:
                owner = mod_owner.get(mod) or mod_owner.get(top) or ""
                # longest namespace prefix (C#)
                if not owner:
                    parts = mod.split(".")
                    for k in range(len(parts), 0, -1):
                        owner = mod_owner.get(".".join(parts[:k]), "")
                        if owner:
                            break
                if owner and owner != e.project:
                    e.scope = "cross"
                    e.resolved_project = owner
                else:
                    e.scope = "third-party"
        elif e.kind == "project_ref":
            tgt = e.target.replace("/", "\\")
            if tgt.lower().endswith(("proj",)):
                stem = PureWindowsPath(tgt).stem.lower()
                owner = mod_owner.get(stem, "")
                if owner and owner != e.project:
                    e.resolved_project = owner
            else:
                owner = mod_owner.get(e.target.lower(), "")
                if owner and owner != e.project:
                    e.resolved_project = owner


# ── renderers ────────────────────────────────────────────────────────────────
def _mermaid(result: LinkMapResult) -> str:
    ids = {p.name: f"P{i}" for i, p in enumerate(result.projects)}
    lines = ["graph LR"]
    for p in result.projects:
        lines.append(f'    {ids[p.name]}["{p.name}"]')
    for (a, b), es in sorted(result.project_links().items()):
        kinds = ", ".join(sorted({e.kind for e in es}))
        lines.append(f'    {ids[a]} -->|"{kinds} ({len(es)})"| {ids[b]}')
    shared = result.shared_resources()[:15]
    for j, (kind, target, projs) in enumerate(shared):
        label = target if len(target) < 48 else target[:45] + "…"
        label = label.replace('"', "'")
        lines.append(f'    R{j}(("{kind}: {label}"))')
        for pn in projs:
            if pn in ids:
                lines.append(f"    {ids[pn]} -.-> R{j}")
    return "\n".join(lines)


def to_markdown(result: LinkMapResult, max_per_kind: int = 60) -> str:
    out = io.StringIO()
    w = out.write
    w(f"# 🕸 {APP_NAME} Link Map\n\n*Generat: {result.generated} · {APP_NAME} v{APP_VERSION}*\n\n")
    w("## Rezumat proiecte\n\n| Proiect | Fisiere | " + " | ".join(KINDS) + " |\n|---|---:|" + "---:|" * len(KINDS) + "\n")
    counts: Dict[str, Counter] = defaultdict(Counter)
    for e in result.edges:
        counts[e.project][e.kind] += 1
    for p in result.projects:
        w(f"| **{p.name}** | {p.files} | " + " | ".join(str(counts[p.name][k]) for k in KINDS) + " |\n")
    links = result.project_links()
    w("\n## Legaturi intre proiecte\n\n")
    if links:
        w("| Din | Catre | Tip | Exemple |\n|---|---|---|---|\n")
        for (a, b), es in sorted(links.items()):
            ex = "; ".join(f"`{e.file}:{e.line}` {e.target[:60]}" for e in es[:3])
            w(f"| {a} | {b} | {', '.join(sorted({e.kind for e in es}))} ({len(es)}) | {ex} |\n")
    else:
        w("_Nicio dependenta directa intre proiectele analizate._\n")
    shared = result.shared_resources()
    w("\n## Resurse comune (folosite de mai multe tool-uri)\n\n")
    if shared:
        w("| Tip | Resursa | Proiecte |\n|---|---|---|\n")
        for kind, target, projs in shared[:150]:
            w(f"| {kind} | `{target[:120]}` | {', '.join(projs)} |\n")
    else:
        w("_Nicio resursa comuna detectata._\n")
    w("\n## Graf\n\n```mermaid\n" + _mermaid(result) + "\n```\n")
    for p in result.projects:
        pe = [e for e in result.edges if e.project == p.name]
        if not pe:
            continue
        w(f"\n## {p.name}\n\n`{p.root}`\n")
        for kind in KINDS:
            ke = [e for e in pe if e.kind == kind]
            if kind == "import":
                ke = [e for e in ke if e.scope in ("cross", "third-party")]
            if not ke:
                continue
            uniq: Dict[str, Edge] = {}
            for e in ke:
                uniq.setdefault(e.target, e)
            w(f"\n### {kind} ({len(uniq)})\n\n")
            for t, e in list(uniq.items())[:max_per_kind]:
                extra = f" → **{e.resolved_project}**" if e.resolved_project else ""
                scope = f" _{e.scope}_" if e.scope else ""
                w(f"- `{t[:160]}`{extra}{scope} — `{e.file}:{e.line}`\n")
            if len(uniq) > max_per_kind:
                w(f"- … inca {len(uniq) - max_per_kind}\n")
    return out.getvalue()


def to_json(result: LinkMapResult) -> str:
    return json.dumps({
        "generated": result.generated,
        "tool": f"{APP_NAME} v{APP_VERSION}",
        "projects": [{"name": p.name, "root": str(p.root), "files": p.files,
                      "modules": sorted(p.modules)[:200], "namespaces": sorted(p.namespaces)} for p in result.projects],
        "project_links": [{"from": a, "to": b, "count": len(es), "kinds": sorted({e.kind for e in es})}
                          for (a, b), es in result.project_links().items()],
        "shared_resources": [{"kind": k, "target": t, "projects": p} for k, t, p in result.shared_resources()],
        "edges": [e.to_dict() for e in result.edges],
    }, indent=2, ensure_ascii=False)


def to_csv(result: LinkMapResult) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["project", "file", "line", "kind", "target", "scope", "resolved_project", "detail"])
    for e in result.edges:
        wr.writerow([e.project, e.file, e.line, e.kind, e.target, e.scope, e.resolved_project, e.detail])
    return buf.getvalue()


def to_html(result: LinkMapResult) -> str:
    e = html.escape
    rows = "".join(
        f"<tr data-kind='{x.kind}'><td>{e(x.project)}</td><td>{e(x.kind)}</td><td class='t'>{e(x.target)}</td>"
        f"<td>{e(x.scope)}</td><td>{e(x.resolved_project)}</td><td>{e(x.file)}:{x.line}</td></tr>"
        for x in result.edges)
    shared = "".join(f"<tr><td>{e(k)}</td><td class='t'>{e(t)}</td><td>{e(', '.join(p))}</td></tr>"
                     for k, t, p in result.shared_resources())
    links = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{len(es)}</td><td>{e(', '.join(sorted({x.kind for x in es})))}</td></tr>"
                    for (a, b), es in sorted(result.project_links().items()))
    kinds_opts = "".join(f"<option>{k}</option>" for k in KINDS)
    return f"""<!DOCTYPE html><html lang="ro"><head><meta charset="UTF-8"><title>{APP_NAME} Link Map</title>
<style>body{{background:#1c1f26;color:#e8edf3;font-family:"Segoe UI",Arial,sans-serif;padding:20px}}
h1,h2{{color:#00c2de}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #3a4050;padding:4px 8px;vertical-align:top}} th{{background:#2a2f3a;color:#7dd3fc;position:sticky;top:0}}
td.t{{word-break:break-all;font-family:Consolas,monospace}} input,select{{background:#262a34;color:#e8edf3;border:1px solid #3a4050;padding:6px}}
.mermaid{{background:#fff;border-radius:8px;padding:10px}}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script></head><body>
<h1>🕸 {APP_NAME} Link Map</h1><p>Generat: {result.generated} · {len(result.projects)} proiecte · {len(result.edges)} legaturi</p>
<h2>Graf</h2><div class="mermaid">{e(_mermaid(result))}</div>
<h2>Legaturi intre proiecte</h2><table><tr><th>Din</th><th>Catre</th><th>Nr.</th><th>Tipuri</th></tr>{links}</table>
<h2>Resurse comune</h2><table><tr><th>Tip</th><th>Resursa</th><th>Proiecte</th></tr>{shared}</table>
<h2>Toate legaturile</h2><p><input id="q" placeholder="filtru text…" size="40"> <select id="k"><option value="">toate tipurile</option>{kinds_opts}</select></p>
<table id="all"><tr><th>Proiect</th><th>Tip</th><th>Tinta</th><th>Scope</th><th>Proiect tinta</th><th>Sursa</th></tr>{rows}</table>
<script>try{{mermaid.initialize({{startOnLoad:true,theme:'default'}});}}catch(e){{}}
function f(){{var q=document.getElementById('q').value.toLowerCase(),k=document.getElementById('k').value;
document.querySelectorAll('#all tr[data-kind]').forEach(function(r){{var ok=(!k||r.dataset.kind==k)&&(!q||r.textContent.toLowerCase().indexOf(q)>=0);r.style.display=ok?'':'none';}});}}
document.getElementById('q').oninput=f;document.getElementById('k').onchange=f;</script></body></html>"""


def save_all(result: LinkMapResult, out_dir: Path, stem: str = "NexusX_LinkMap") -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = []
    for ext, fn in ((".md", to_markdown), (".json", to_json), (".csv", to_csv), (".html", to_html)):
        p = out_dir / f"{stem}_{ts}{ext}"
        p.write_text(fn(result), encoding="utf-8-sig" if ext == ".csv" else "utf-8")
        paths.append(p)
    return paths


__all__ = ["Edge", "LinkMapResult", "ProjectInfo", "analyse", "to_markdown", "to_json", "to_csv",
           "to_html", "save_all", "KINDS", "DEFAULT_EXCLUDED"]
