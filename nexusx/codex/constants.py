# -*- coding: utf-8 -*-
"""
Extension groups, exclusions and preset export pairs.
Ported 1:1 from UCeX v6.7, plus: name-based matching (Dockerfile, Makefile,
requirements.txt …) which v6.7 listed but could never match by suffix.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Set

EXT_GROUPS: Dict[str, List[str]] = {
    "Python": [".py", ".pyw", ".pyi", ".pyx", ".pxd", ".ipynb"],
    "C# / .NET": [".cs", ".csproj", ".vbproj", ".fsproj", ".sln",
                  ".xaml", ".axaml", ".resx", ".resw", ".targets",
                  ".props", ".tasks", ".pubxml", ".vstemplate",
                  ".vsixmanifest", ".vsct", ".snk", ".manifest",
                  ".appxmanifest", ".rdlc", ".xsd", ".wsdl",
                  ".tt", ".t4", ".ttinclude", ".nuspec",
                  ".globalconfig", ".ruleset", ".editorconfig"],
    "Web": [".html", ".htm", ".css", ".scss", ".sass", ".less",
            ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".astro",
            ".gs", ".mjs", ".cjs"],
    "Config": [".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
               ".conf", ".env", ".xml", ".plist", ".reg", ".inf",
               ".config", ".gitignore", ".gitattributes", ".properties"],
    "Docs": [".md", ".rst", ".adoc", ".tex", ".org",
             ".txt", ".log", ".nfo", ".readme"],
    "Data": [".csv", ".tsv", ".sql", ".ddl", ".dml",
             ".psql", ".plsql", ".graphql", ".gql",
             ".prisma", ".db", ".avro", ".parquet",
             ".proto", ".thrift"],
    "Shell": [".sh", ".bash", ".zsh", ".fish",
              ".ps1", ".psm1", ".psd1", ".bat", ".cmd", ".vbs", ".ahk"],
    "Backend": [".java", ".kt", ".kts", ".scala", ".groovy",
                ".vb", ".fs", ".fsx", ".go", ".rs", ".swift",
                ".m", ".mm", ".cpp", ".cc", ".cxx", ".c",
                ".h", ".hpp", ".hxx", ".php", ".rb", ".pl",
                ".pm", ".lua", ".r", ".jl"],
    "DevOps": [".dockerfile", "dockerfile", ".tf", ".tfvars",
               ".hcl", ".nomad", ".k8s", ".helm",
               "makefile", "rakefile", "gemfile", "podfile",
               ".gradle", ".maven", ".ant"],
    "Mobile": [".dart", ".storyboard", ".xib"],
    "Notebook": [".ipynb", ".nb", ".rmd", ".qmd", ".jmd", ".pluto"],
    "Game / 3D": [".gd", ".gdscript", ".hlsl", ".glsl",
                  ".vert", ".frag", ".shader", ".fx"],
    "Package": [".pyproject", ".setup", ".cargo", ".lock",
                "requirements.txt", "package.json", "composer.json",
                ".nupkg"],
    "Misc": [".diff", ".patch", ".ics", ".vcf", ".eml",
             ".srt", ".vtt", ".ass", ".sub"],
}

ALL_EXTS: List[str] = list(dict.fromkeys(e for grp in EXT_GROUPS.values() for e in grp))

DEFAULT_EXCLUDED = "node_modules,.git,__pycache__,.vs,bin,obj,dist,build,.idea,.vscode,packages"

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg"}

_CREATIVITY = Path.home() / "OneDrive - Siemens AG" / "__myCreativity"
_EXPORT = _CREATIVITY / "codeexport"

DEFAULT_EXPORT_PAIRS: List[Dict[str, str]] = [
    {"name": "AutoPilotDC", "source": str(_CREATIVITY / "AutoPilot" / "AutoPilotDC_C#"), "export": str(_EXPORT / "AutoPilotDC")},
    {"name": "BVA_Extractor", "source": str(_CREATIVITY / "Ns_B_BVA_extractor"), "export": str(_EXPORT / "BVA_Extractor")},
    {"name": "DataCleansing", "source": r"D:\TestautoDev", "export": str(_EXPORT / "DataCleansing")},
    {"name": "OneNoteExtractor", "source": str(_CREATIVITY / "OneNote_Extractor"), "export": str(_EXPORT / "OneNoteExtractor")},
    {"name": "TruePortal", "source": str(_CREATIVITY / "TruePortal"), "export": str(_EXPORT / "TruePortal")},
    {"name": "DevPilot", "source": str(_CREATIVITY / "DevPilot"), "export": str(_EXPORT / "DevPilot")},
    {"name": "DevPilot_AI_Agent", "source": str(_CREATIVITY / "DevPilot_AI_Agent"), "export": str(_EXPORT / "DevPilot_AI_Agent")},
    {"name": "MasterOrchestrator", "source": str(_CREATIVITY / "MasterOrchestrator"), "export": str(_EXPORT / "MasterOrchastrator")},
    {"name": "UCeX5", "source": str(_CREATIVITY / "UCeX" / "UCeX_v5_Siemens"), "export": str(_EXPORT / "UCeX")},
    {"name": "UCeX6", "source": str(_CREATIVITY / "UCeX" / "UCeX_v6_Siemens"), "export": str(_EXPORT / "UCeX")},
    {"name": "ULaE", "source": str(_CREATIVITY / "UCeX" / "ULaE__Siemens"), "export": str(_EXPORT / "ULaE")},
    {"name": "NexusX", "source": str(_CREATIVITY / "UCeX" / "NexusX"), "export": str(_EXPORT / "NexusX")},
    {"name": "TruePortal C#", "source": str(_CREATIVITY / "TruePortal_CS"), "export": str(_EXPORT / "TruePortalC#")},
    {"name": "CloudDF", "source": str(_CREATIVITY / "CloudDF" / "CloudDupeFinder"), "export": str(_EXPORT / "CloudDF")},
    {"name": "myCreativity", "source": str(_CREATIVITY), "export": str(_EXPORT / "myCreativity")},
]

_LANG_MAP = {
    ".py": "python", ".pyw": "python", ".pyi": "python", ".ipynb": "json",
    ".cs": "csharp", ".csproj": "xml", ".vbproj": "xml", ".fsproj": "xml", ".sln": "text",
    ".xaml": "xml", ".axaml": "xml", ".resx": "xml", ".props": "xml", ".targets": "xml",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".gs": "javascript",
    ".ts": "typescript", ".jsx": "jsx", ".tsx": "tsx",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss", ".less": "less",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".ini": "ini",
    ".md": "markdown", ".rst": "rst",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".bat": "batch", ".cmd": "batch",
    ".ps1": "powershell", ".psm1": "powershell", ".vbs": "vbscript", ".ahk": "autohotkey",
    ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".h": "c", ".hpp": "cpp",
    ".rs": "rust", ".go": "go", ".java": "java", ".kt": "kotlin", ".swift": "swift",
    ".rb": "ruby", ".php": "php", ".lua": "lua", ".r": "r", ".dart": "dart",
    ".sql": "sql", ".graphql": "graphql", ".xml": "xml", ".vue": "vue", ".svelte": "svelte",
    ".tf": "hcl", ".hcl": "hcl", ".vb": "vbnet", ".fs": "fsharp",
}


def detect_lang(path: Path) -> str:
    name = path.name.lower()
    if name == "dockerfile" or name.endswith(".dockerfile"):
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    return _LANG_MAP.get(path.suffix.lower(), "text")


def ext_key(path: Path) -> str:
    """Key used by the extension filter: suffix, or full lower-case name for suffix-less specials."""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in _NAME_KEYS:
        return name
    return suffix or name


_NAME_KEYS: Set[str] = {e for e in ALL_EXTS if not e.startswith(".")}


def matches_exts(path: Path, active: Iterable[str]) -> bool:
    active_set = active if isinstance(active, set) else set(active)
    name = path.name.lower()
    return path.suffix.lower() in active_set or name in active_set


def is_code_file(path: Path) -> bool:
    return matches_exts(path, set(ALL_EXTS))
