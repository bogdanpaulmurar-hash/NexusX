# -*- coding: utf-8 -*-
"""LinkRecord — ULaE v2.0 model, extended (all original fields kept, same names)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# Status vocabulary (ULaE strings kept so exports / filters stay compatible)
OK_STATUSES = {"OK", "Browser OK", "Bookmark OK", "OK (Download)", "Download completed",
               "Internal Bookmark", "OK (local file)", "Mailto (syntax OK)", "Redirect with content"}
BROKEN_STATUSES = {"Broken", "Broken Bookmark", "Page error", "Connection failed", "Timeout",
                   "Browser error", "SSL error", "Broken (path not found)", "Invalid mailto"}
AUTH_STATUSES = {"Authentication required", "Access denied"}
WARN_STATUSES = {"Anchor missing", "Rate limited", "Not checked", "Local / Non-web", "Unreachable share"}

STATUS_CHOICES = [
    "Browser OK", "OK", "Redirect with content", "Authentication required", "Access denied",
    "Page error", "Broken", "Broken Bookmark", "Anchor missing", "Timeout", "OK (Download)",
    "Internal Bookmark", "Bookmark OK", "OK (local file)", "Broken (path not found)", "Not checked",
]


def status_group(status: str) -> str:
    s = status or ""
    if s in AUTH_STATUSES or "Authentication" in s or "Access denied" in s:
        return "auth"
    if s in BROKEN_STATUSES or s.startswith("Broken"):
        return "broken"
    if "Download" in s:
        return "download"
    if s in OK_STATUSES or s.startswith("OK"):
        return "ok"
    if s == "Not checked" or not s:
        return "pending"
    return "warn"


@dataclass
class LinkRecord:
    file: str
    path: str
    location: str
    url: str
    anchor: str = ""
    context: str = ""
    source: str = "Text URL"
    status: str = "Not checked"
    http_code: str = ""
    final_url: str = ""
    evidence: str = ""
    download_status: str = "Not a download"
    download_filename: str = ""
    download_size: str = ""
    error: str = ""
    notes: str = ""
    issues: List[str] = field(default_factory=list)
    # NexusX additions
    section: str = ""            # nearest Word heading of the link's location
    target_section: str = ""     # for internal links: heading/text of the target
    response_ms: int = 0
    content_type: str = ""
    redirects: List[str] = field(default_factory=list)
    parent_url: str = ""         # for links discovered by page crawling
    occurrences: int = 1
    checked_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def group(self) -> str:
        return status_group(self.status)

    def format_location_display(self) -> str:
        loc = self.location or ""
        if self.section:
            loc = f"{loc} § {self.section[:60]}"
        if self.anchor:
            return f"{loc} | Text: {self.anchor[:120]}"
        if self.context:
            return f"{loc} | Context: {self.context[:140]}"
        return loc

    @property
    def is_web(self) -> bool:
        return self.url.lower().startswith(("http://", "https://", "ftp://", "www."))
