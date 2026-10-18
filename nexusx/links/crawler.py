# -*- coding: utf-8 -*-
"""
Page link expansion — NEW in NexusX.

"A link that itself contains many links": fetch a page (portal, wiki, SharePoint page,
index.html), collect every link on it (optionally N levels deep, same domain only) and
add them to the workspace so they can all be verified in one run.
Uses plain HTTP first; if the page needs SSO or is built by JavaScript, it can fall back
to the Playwright browser session (same cookies as BROWSER VERIFY).
"""
from __future__ import annotations

from collections import deque
from typing import Callable, List, Optional, Set
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import HTTPSHandler, Request, build_opener

from .checker import USER_AGENT, _CTX, _is_login
from .extractor import _HtmlLinks
from .models import LinkRecord

Log = Optional[Callable[[str], None]]


def _fetch(url: str, timeout: int) -> tuple:
    opener = build_opener(HTTPSHandler(context=_CTX))
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"})
    with opener.open(req, timeout=timeout) as resp:
        final = resp.geturl()
        ctype = resp.headers.get("Content-Type", "") or ""
        if "html" not in ctype.lower():
            return final, ""
        raw = resp.read(3_000_000)
        return final, raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")


def expand_page(start_url: str, timeout: int = 20, same_domain: bool = True, max_links: int = 300,
                depth: int = 1, browser=None, use_browser_fallback: bool = True,
                on_log: Log = None, should_stop: Optional[Callable[[], bool]] = None) -> List[LinkRecord]:
    def log(m):
        if on_log:
            on_log(m)

    if start_url.lower().startswith("www."):
        start_url = "https://" + start_url
    root_host = urlparse(start_url).netloc.lower()
    seen_pages: Set[str] = set()
    seen_links: Set[str] = set()
    out: List[LinkRecord] = []
    queue = deque([(start_url, 0)])

    while queue and len(out) < max_links:
        if should_stop and should_stop():
            break
        page_url, level = queue.popleft()
        key = urldefrag(page_url)[0]
        if key in seen_pages:
            continue
        seen_pages.add(key)
        anchors: List[dict] = []
        final = page_url
        try:
            final, html_text = _fetch(page_url, timeout)
            if _is_login(final) or not html_text:
                raise RuntimeError("login or non-HTML")
            parser = _HtmlLinks()
            parser.feed(html_text)
            base = parser.base or final
            for tag, href, line, text in parser.links:
                if tag in ("a", "area"):
                    anchors.append({"href": urljoin(base, href.strip()), "text": text, "line": line})
            log(f"[CRAWL] {page_url} → {len(anchors)} links (HTTP)")
        except Exception as e:  # noqa: BLE001
            if browser is not None and use_browser_fallback:
                log(f"[CRAWL] HTTP failed for {page_url} ({e}); rendering in browser session…")
                anchors = [dict(a, line=0) for a in browser.extract_links(page_url, headless=True, timeout_sec=timeout, on_log=on_log)]
                log(f"[CRAWL] {page_url} → {len(anchors)} links (browser)")
            else:
                log(f"[CRAWL ERROR] {page_url}: {e}")
                continue

        page_label = f"[Page] {urlparse(page_url).netloc}{urlparse(page_url).path[:60]}"
        for n, a in enumerate(anchors, 1):
            href = a.get("href", "")
            if not href or href.lower().startswith(("javascript:", "data:", "tel:")):
                continue
            href_nofrag, frag = urldefrag(href)
            if not frag and href_nofrag == urldefrag(final)[0]:
                continue
            if href in seen_links:
                continue
            host = urlparse(href).netloc.lower()
            if same_domain and host and host != root_host and level > 0:
                continue
            seen_links.add(href)
            out.append(LinkRecord(file=page_label, path=page_url, location=f"Link #{n}" + (f" (line {a['line']})" if a.get("line") else ""),
                                  url=href, anchor=(a.get("text") or "")[:200], source=f"Page crawl (level {level + 1})",
                                  parent_url=page_url))
            if len(out) >= max_links:
                break
            if level + 1 < depth and host == root_host and href.lower().startswith("http"):
                queue.append((href, level + 1))
    return out
