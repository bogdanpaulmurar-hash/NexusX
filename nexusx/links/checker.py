# -*- coding: utf-8 -*-
"""
HTTP verification (ULaE v2.0 http_probe), improved:
  • parallel checking with a thread pool + per-URL cache (same URL in 30 docs → 1 request)
  • retries with back-off for timeouts / 429 / 5xx
  • redirect chain + response time + content type recorded
  • login-redirect detection (Microsoft Entra / ADFS / OAuth) → "Authentication required"
    (v2.0 reported these as "Redirect with content" / OK)
  • smarter soft-404: strong phrases in title/headings, weak phrases only on short pages
    (fewer false "Page error" on long pages that merely contain the word "forbidden");
    German + Romanian SharePoint/Confluence messages added
  • #fragment check (anchor exists on the target page)
  • mailto: syntax, file:// and UNC paths (existence), SSL errors reported clearly
"""
from __future__ import annotations

import datetime
import os
import re
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .models import LinkRecord

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0.0.0 Safari/537.36 NexusX/1.0")

# strong = reliable even in body; weak = only in title/headings or very short pages
STRONG_BAD = (
    "page not found", "404 not found", "could not be found", "item does not exist",
    "this content is no longer available", "the page you requested could not be found",
    "file not found", "page does not exist", "this page doesn't exist",
    "seite nicht gefunden", "die seite wurde nicht gefunden", "datei nicht gefunden",
    "diese seite ist nicht vorhanden", "element ist nicht vorhanden", "existiert nicht",
    "pagina nu a fost gasita", "pagina nu a fost găsită", "pagina nu exista",
    "sorry, something went wrong", "leider ist ein problem aufgetreten",
    "you need permission to access this item", "sie benötigen eine berechtigung",
    "access denied", "zugriff verweigert", "permission denied", "keine berechtigung",
)
WEAK_BAD = ("something went wrong", "request failed", "unauthorized", "forbidden", "not found", "error 404")
COMMON_BAD_KEYWORDS = STRONG_BAD + WEAK_BAD  # kept for compatibility with ULaE imports

LOGIN_HOSTS = ("login.microsoftonline.com", "login.live.com", "login.windows.net", "adfs.", "/adfs/",
               "loginoidc", "/oauth2/", "/saml2", "/sso/", "okta.com", "accounts.google.com/servicelogin",
               "/_forms/default.aspx", "/_layouts/15/authenticate.aspx")
DOWNLOAD_TYPES = ("application/octet-stream", "application/zip", "application/pdf", "application/x-msdownload",
                  "application/vnd.openxmlformats", "application/msword", "application/vnd.ms-")
TRANSIENT_CODES = {429, 500, 502, 503, 504}
MAILTO_RE = re.compile(r"^mailto:([A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})(?:[,;].*)?(?:\?.*)?$", re.I)


class _RecordingRedirect(HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.chain: List[str] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append(f"{code} → {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _ssl_context() -> ssl.SSLContext:
    """System trust store (Windows certificate store incl. corporate root CAs)."""
    try:
        import truststore  # type: ignore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        ctx = ssl.create_default_context()
        try:
            ctx.load_default_certs()
        except Exception:
            pass
        return ctx


_CTX = _ssl_context()


def _visible(text: str) -> Tuple[str, List[str], str]:
    title_m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    title = re.sub(r"<[^>]+>", " ", title_m.group(1)).strip() if title_m else ""
    title = " ".join(title.split())
    heads = [" ".join(re.sub(r"<[^>]+>", " ", h).split()) for h in
             re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", text, re.I | re.S)]
    heads = [h for h in heads if h]
    body = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>|<[^>]+>", " ", text, flags=re.I | re.S)
    body = " ".join(body.split())
    return title, heads, body


def classify_page(title: str, heads: List[str], body: str) -> str:
    """Return the matched bad phrase or '' (soft-404 / access-denied detection)."""
    th = f"{title} {' '.join(heads[:3])}".lower()
    low = body.lower()
    for k in STRONG_BAD:
        if k in th or k in low[:4000]:
            return k
    for k in WEAK_BAD:
        if k in th:
            return k
        if len(low) < 1500 and k in low:
            return k
    return ""


def _is_login(url: str) -> bool:
    low = (url or "").lower()
    return any(h in low for h in LOGIN_HOSTS)


def _check_local(rec: LinkRecord) -> LinkRecord:
    u = rec.url
    if u.lower().startswith("file:"):
        p = urlparse(u)
        path = unquote(p.path)
        if p.netloc and p.netloc.lower() != "localhost":
            path = f"\\\\{p.netloc}{path.replace('/', chr(92))}"
        elif re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
    else:
        path = u
    try:
        exists = Path(path).exists()
    except OSError:
        exists = False
    rec.http_code = "Local"
    if exists:
        rec.status = "OK (local file)"
        rec.evidence = f"Path exists: {path}"
        rec.error = ""
    elif path.startswith("\\\\"):
        rec.status = "Broken (path not found)"
        rec.error = f"Network path not reachable or not found: {path}"
    else:
        rec.status = "Broken (path not found)"
        rec.error = f"File not found: {path}"
    return rec


def http_probe(rec: LinkRecord, timeout: int = 20, retries: int = 1, check_fragment: bool = True) -> LinkRecord:
    """Fast HTTP probe. Same signature as ULaE (extra kwargs optional)."""
    rec.checked_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target = rec.url.strip()
    low = target.lower()

    if low.startswith("#bookmark=") or low.startswith("#"):
        if not rec.status or rec.status == "Not checked":
            rec.status = "Bookmark OK"
        rec.http_code = "Internal"
        if not rec.evidence:
            rec.evidence = f"Document Internal Bookmark target: {target.replace('#bookmark=', '')}"
        return rec
    if low.startswith("mailto:"):
        rec.http_code = "Mail"
        if MAILTO_RE.match(target):
            rec.status, rec.evidence, rec.error = "Mailto (syntax OK)", f"E-mail address: {target[7:].split('?')[0]}", ""
        else:
            rec.status, rec.error = "Invalid mailto", "Malformed e-mail address"
        return rec
    if low.startswith("file:") or target.startswith("\\\\"):
        return _check_local(rec)
    if low.startswith("www."):
        target = "https://" + target
        rec.url = target

    frag = urlparse(target).fragment
    req_url = target.split("#")[0] if frag else target
    attempt = 0
    while True:
        attempt += 1
        redirect = _RecordingRedirect()
        opener = build_opener(redirect, HTTPSHandler(context=_CTX))
        req = Request(req_url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,ro;q=0.7",
        })
        t0 = time.perf_counter()
        try:
            with opener.open(req, timeout=timeout) as resp:
                rec.response_ms = int((time.perf_counter() - t0) * 1000)
                code = resp.getcode()
                final = resp.geturl()
                rec.http_code = str(code)
                rec.final_url = final
                rec.redirects = redirect.chain[:10]
                disp = resp.headers.get("Content-Disposition", "") or ""
                ctype = resp.headers.get("Content-Type", "") or ""
                clen = resp.headers.get("Content-Length", "") or ""
                rec.content_type = ctype.split(";")[0]

                if _is_login(final):
                    rec.status = "Authentication required"
                    rec.evidence = f"Redirected to corporate login: {urlparse(final).netloc}"
                    rec.error = "Requires SSO login — use ONE-TIME SSO LOGIN + BROWSER VERIFY"
                    return rec

                if "attachment" in disp.lower() or any(t in ctype.lower() for t in DOWNLOAD_TYPES):
                    m = re.search(r"filename\*?=(?:UTF-8'')?[\"']?([^\";\r\n]+)", disp, re.I)
                    fname = unquote(m.group(1).strip()) if m else (Path(urlparse(final).path).name or "downloaded_file")
                    rec.download_status = "Download stream detected"
                    rec.download_filename = fname
                    rec.download_size = f"{int(clen) // 1024} KB" if clen.isdigit() else ""
                    rec.status = "OK (Download)"
                    rec.evidence = f"Download detected | File: {fname} ({rec.download_size or '?'}) | {rec.content_type}"
                    rec.error = ""
                    return rec

                raw = resp.read(256000)
                charset = resp.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
                title, heads, body = _visible(text)
                bad = classify_page(title, heads, body)
                ev = [v for v in (title, heads[0] if heads else "", body[:250]) if v]
                rec.evidence = " | ".join(ev)[:600]
                if any(k in title.lower() for k in ("sign in to your account", "pick an account", "anmelden bei ihrem konto",
                                                    "konto auswählen", "sign in", "log in")) and len(body) < 6000 or \
                        "sign in to your account" in body[:2000].lower():
                    rec.status = "Authentication required"
                    rec.error = "Login page returned"
                elif bad:
                    rec.status = "Page error"
                    rec.error = f"Visible page message: {bad}"
                elif check_fragment and frag and "html" in ctype.lower() and \
                        not re.search(r"""(?:id|name)\s*=\s*["']%s["']""" % re.escape(unquote(frag)), text) and \
                        len(raw) < 256000:
                    rec.status = "Anchor missing"
                    rec.error = f"Page loads but anchor #{frag} was not found"
                elif final.split("#")[0].rstrip("/") != req_url.rstrip("/"):
                    rec.status = "Redirect with content"
                    rec.error = ""
                else:
                    rec.status = "OK"
                    rec.error = ""
                return rec
        except HTTPError as e:
            rec.response_ms = int((time.perf_counter() - t0) * 1000)
            rec.http_code = str(e.code)
            rec.final_url = getattr(e, "url", "") or target
            rec.redirects = redirect.chain[:10]
            if e.code in TRANSIENT_CODES and attempt <= retries:
                time.sleep(min(8, 1.5 * attempt * (3 if e.code == 429 else 1)))
                continue
            if _is_login(rec.final_url) or e.code == 401:
                rec.status, rec.error = "Authentication required", f"HTTP {e.code} {e.reason}"
            elif e.code == 403:
                rec.status, rec.error = "Access denied", "HTTP 403 Forbidden"
            elif e.code == 404 or e.code == 410:
                rec.status, rec.error = "Broken", f"HTTP {e.code} {'Not Found' if e.code == 404 else 'Gone'}"
            elif e.code == 429:
                rec.status, rec.error = "Rate limited", "HTTP 429 Too Many Requests"
            elif e.code in (405, 501):
                # some servers refuse GET for bots but the resource exists
                rec.status, rec.error = "Redirect with content", f"HTTP {e.code} (server refuses automated GET)"
            else:
                rec.status, rec.error = "Broken", f"HTTP {e.code} {e.reason}"
            return rec
        except (socket.timeout, TimeoutError) as e:
            if attempt <= retries:
                continue
            rec.status, rec.error = "Timeout", f"No response within {timeout}s ({e})"
            return rec
        except URLError as e:
            reason = e.reason
            err = str(reason)
            if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in err.upper() or "SSL" in err.upper():
                rec.status, rec.error = "SSL error", f"TLS/certificate problem: {err} (pip install truststore for corporate CAs)"
            elif "timed out" in err.lower():
                if attempt <= retries:
                    continue
                rec.status, rec.error = "Timeout", err
            elif isinstance(reason, socket.gaierror) or "getaddrinfo" in err or "Name or service" in err:
                rec.status, rec.error = "Connection failed", f"Host not resolvable (intranet/VPN?): {err}"
            else:
                rec.status, rec.error = "Connection failed", err
            return rec
        except Exception as e:  # noqa: BLE001
            err = str(e)
            if "timed out" in err.lower() and attempt <= retries:
                continue
            rec.status = "Timeout" if "timed out" in err.lower() else "Connection failed"
            rec.error = err
            return rec


class ProbeCache:
    """Thread-safe URL → result cache so identical URLs are probed once per run."""

    FIELDS = ("status", "http_code", "final_url", "evidence", "download_status", "download_filename",
              "download_size", "error", "response_ms", "content_type", "redirects", "checked_at")

    def __init__(self):
        self._lock = threading.Lock()
        self._events: Dict[str, threading.Event] = {}
        self._data: Dict[str, Dict] = {}

    def run(self, rec: LinkRecord, fn: Callable[[LinkRecord], LinkRecord]) -> LinkRecord:
        key = rec.url.strip()
        if key.startswith("#"):
            return fn(rec)
        with self._lock:
            ev = self._events.get(key)
            owner = ev is None
            if owner:
                ev = threading.Event()
                self._events[key] = ev
        if owner:
            fn(rec)
            with self._lock:
                self._data[key] = {f: getattr(rec, f) for f in self.FIELDS}
            ev.set()
        else:
            ev.wait()
            for f, v in self._data.get(key, {}).items():
                setattr(rec, f, list(v) if isinstance(v, list) else v)
        return rec


def check_many(records: Iterable[LinkRecord], timeout: int = 20, workers: int = 8, retries: int = 1,
               check_fragment: bool = True,
               on_progress: Optional[Callable[[LinkRecord, int, int], None]] = None,
               should_stop: Optional[Callable[[], bool]] = None) -> int:
    """Probe many records in parallel. Returns number checked."""
    recs = list(records)
    total = len(recs)
    cache = ProbeCache()
    done = 0
    lock = threading.Lock()

    def task(r: LinkRecord) -> LinkRecord:
        if should_stop and should_stop():
            return r
        return cache.run(r, lambda x: http_probe(x, timeout=timeout, retries=retries, check_fragment=check_fragment))

    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), 32))) as ex:
        futures = [ex.submit(task, r) for r in recs]
        for fut in as_completed(futures):
            try:
                r = fut.result()
            except Exception:  # noqa: BLE001
                continue
            with lock:
                done += 1
                n = done
            if on_progress:
                on_progress(r, n, total)
    return done


def sanitize_console_title() -> None:
    """ULaE fix: Node/libuv assertion with odd console titles when Playwright starts."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("NexusX_Worker")
        except Exception:
            pass
