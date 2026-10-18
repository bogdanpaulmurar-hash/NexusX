# -*- coding: utf-8 -*-
"""
Secret redaction for code exports.

Exports are pasted into AI assistants (SiemensGPT, Claude …). Code that talks to
company systems often carries passwords, tokens or connection strings; this
masks the *values* while keeping the structure so the export stays useful for
mapping connections between tools.
"""
from __future__ import annotations

import re
from typing import List, Tuple

MASK = "«REDACTED»"

_PATTERNS: List[Tuple[str, "re.Pattern[str]", str]] = [
    # -----BEGIN PRIVATE KEY----- blocks
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "-----BEGIN PRIVATE KEY-----" + MASK + "-----END PRIVATE KEY-----"),
    # key = "value" / key: 'value' for sensitive key names
    ("assignment", re.compile(
        r"""(?ix)
        (?P<key>["']?[\w.\-]*(?:password|passwd|pwd|secret|token|api[_\-]?key|apikey|access[_\-]?key|
             client[_\-]?secret|private[_\-]?key|auth[_\-]?key|sas|bearer|credential)s?[\w.\-]*["']?)
        (?P<sep>\s*(?:=|:|=>|:=)\s*)
        (?P<q>["'])(?P<val>[^"'\r\n]{3,})(?P=q)
        """), r"\g<key>\g<sep>\g<q>" + MASK + r"\g<q>"),
    # Authorization: Bearer xxx / Basic xxx
    ("auth_header", re.compile(r"(?i)(authorization\s*[:=]\s*[\"']?\s*(?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=\-]{8,}"),
     r"\1" + MASK),
    # connection strings  Password=...; Pwd=...;
    ("conn_pwd", re.compile(r"(?i)((?:password|pwd|accountkey|sharedaccesskey)\s*=\s*)[^;\"'\s]+"), r"\1" + MASK),
    # credentials inside URLs  scheme://user:pass@host
    ("url_creds", re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@\"']+:)[^@\s/\"']+(@)"), r"\1" + MASK + r"\2"),
    # well-known token formats
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), MASK),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"), MASK),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"), MASK),
    ("openai_like", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}\b"), MASK),
    ("google_api", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), MASK),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), MASK),
]


def redact(text: str) -> Tuple[str, int]:
    """Return (redacted_text, number_of_replacements)."""
    total = 0
    for _name, pat, repl in _PATTERNS:
        text, n = pat.subn(repl, text)
        total += n
    return text, total
