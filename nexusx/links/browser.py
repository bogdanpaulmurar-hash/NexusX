# -*- coding: utf-8 -*-
"""
Playwright browser verification (ULaE v2.0 BrowserEngine) — same behaviour and the same
persistent profile (~/.ulae_playwright_profile) so existing SSO cookies keep working.

Improvements:
  • choose engine/channel: bundled Chromium, Microsoft Edge ("msedge") or Chrome —
    Edge uses the corporate device identity, which often makes SSO pass silently
  • single page reused for the batch + short network-idle wait for SPA pages (SharePoint, Confluence)
  • HTTP status of the main document captured (v2.0 only looked at the DOM)
  • login detection shared with the HTTP checker
  • extract_links(): collect all <a href> of a rendered page (for JS-built pages)
"""
from __future__ import annotations

import datetime
import re
import time
from pathlib import Path
from typing import Callable, List, Optional

from ..paths import PLAYWRIGHT_PROFILE
from .checker import LOGIN_HOSTS, classify_page, sanitize_console_title
from .models import LinkRecord

Log = Optional[Callable[[str], None]]


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


class BrowserEngine:
    def __init__(self, profile_dir: Optional[Path] = None, channel: str = "chromium"):
        self.profile_dir = profile_dir or PLAYWRIGHT_PROFILE
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.channel = channel

    # ── context ──
    def _launch(self, pw, headless: bool):
        kwargs = dict(headless=headless, accept_downloads=True,
                      args=["--disable-blink-features=AutomationControlled"],
                      viewport={"width": 1366, "height": 900})
        if self.channel in ("msedge", "chrome"):
            try:
                return pw.chromium.launch_persistent_context(str(self.profile_dir), channel=self.channel, **kwargs)
            except Exception:
                pass  # fall back to bundled chromium
        return pw.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)

    # ── one page ──
    def _verify_page(self, page, rec: LinkRecord, timeout_sec: int, headless: bool, on_log: Log = None) -> LinkRecord:
        def log(m):
            if on_log:
                on_log(m)

        rec.checked_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        target = rec.url
        if target.startswith("#"):
            rec.status, rec.http_code = "Internal Bookmark", "N/A"
            if not rec.evidence:
                rec.evidence = f"Document Internal Bookmark target: {target.replace('#bookmark=', '')}"
            return rec
        if not target.lower().startswith(("http://", "https://", "ftp://", "www.")):
            rec.status, rec.http_code = "Local / Non-web", "N/A"
            return rec
        if target.startswith("www."):
            target = "https://" + target

        log(f"[BROWSER {'HEADLESS' if headless else 'VISIBLE'}] Checking: {target}")
        download_event = [None]

        def on_download(d):
            download_event[0] = d

        page.on("download", on_download)
        t0 = time.perf_counter()
        try:
            resp = None
            try:
                resp = page.goto(target, wait_until="domcontentloaded", timeout=min(timeout_sec, 30) * 1000)
            except Exception as e:  # noqa: BLE001
                low = str(e).lower()
                if "net::err_aborted" not in low and "download" not in low:
                    log(f"[BROWSER NAV NOTE] {e}")
            if resp is not None:
                try:
                    rec.http_code = str(resp.status)
                    rec.content_type = (resp.headers.get("content-type") or "").split(";")[0]
                except Exception:
                    pass
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            rec.response_ms = int((time.perf_counter() - t0) * 1000)

            deadline = time.time() + min(timeout_sec, 20)
            done = False
            while time.time() < deadline:
                if download_event[0]:
                    d = download_event[0]
                    fname = d.suggested_filename or Path(target.split("?")[0]).name or "download"
                    rec.status = rec.download_status = "Download completed"
                    rec.download_filename = fname
                    rec.evidence = f"Download verified in browser | File: {fname}"
                    rec.error = ""
                    log(f"[BROWSER SUCCESS] Download detected: {fname}")
                    return rec
                try:
                    cur = page.url
                    body = page.locator("body").inner_text(timeout=2500)
                except Exception:
                    time.sleep(0.8)
                    continue
                low = f"{cur} {body[:3000]}".lower()
                if any(k in cur.lower() for k in LOGIN_HOSTS) or \
                        any(k in low for k in ("sign in to your account", "permissionviolation", "pick an account")):
                    if headless:
                        rec.status = "Authentication required"
                        rec.final_url = cur
                        if not rec.evidence or "redirect" in rec.evidence.lower():
                            rec.evidence = "Corporate login / SSO required"
                        rec.error = "Requires user SSO login session"
                        done = True
                        break
                    time.sleep(1.0)  # interactive: wait for the user to finish MFA
                    continue
                title = page.title()
                try:
                    heading = page.locator('h1,h2,[role="heading"]').first.inner_text(timeout=1000)
                except Exception:
                    heading = ""
                bad = classify_page(title, [heading] if heading else [], body)
                lines = [re.sub(r"\s+", " ", q).strip() for q in body.splitlines()]
                lines = [q for q in lines if len(q) >= 20]
                meaningful = next((q for q in lines if q.lower() not in ("skip to main content", "skip ribbon commands")), "")
                ev = [q for q in (title, heading, meaningful) if q]
                if ev:
                    rec.evidence = " | ".join(ev)[:600]
                rec.final_url = cur
                if bad:
                    rec.status, rec.error = "Page error", f"Visible page message: {bad}"
                elif rec.http_code in ("404", "410"):
                    rec.status, rec.error = "Broken", f"HTTP {rec.http_code}"
                else:
                    rec.status, rec.error = "Browser OK", ""
                done = True
                break
            if not done:
                cur = page.url
                if any(k in cur.lower() for k in LOGIN_HOSTS):
                    rec.status = "Authentication required"
                    rec.final_url = cur
                    if not rec.evidence or "redirect" in rec.evidence.lower():
                        rec.evidence = "Corporate login / SSO required"
                    rec.error = "Login not completed before timeout"
                else:
                    rec.status, rec.error = "Timeout", "Browser page did not finish loading before timeout"
        except Exception as e:  # noqa: BLE001
            rec.status, rec.error = "Browser error", str(e)
            log(f"[BROWSER ERROR] {e}")
        finally:
            try:
                page.remove_listener("download", on_download)
            except Exception:
                pass
        return rec

    # ── batch / single / auth (ULaE API) ──
    def verify_batch(self, records: List[LinkRecord], timeout_sec: int = 20, headless: bool = True,
                     on_log: Log = None, on_progress=None, should_stop=None) -> None:
        def log(m):
            if on_log:
                on_log(m)
        sanitize_console_title()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("[BROWSER ERROR] Playwright is not installed (pip install playwright && playwright install chromium).")
            return
        total = len(records)
        log(f"[BROWSER] Launching single browser session ({self.channel}, headless={headless}) for {total} links...")
        try:
            with sync_playwright() as pw:
                ctx = self._launch(pw, headless)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                for idx, rec in enumerate(records, 1):
                    if should_stop and should_stop():
                        log("[BROWSER] Batch interrupted by user.")
                        break
                    if rec.url.startswith("#"):
                        rec.status, rec.http_code = "Internal Bookmark", "N/A"
                    else:
                        try:
                            if page.is_closed():
                                page = ctx.new_page()
                        except Exception:
                            page = ctx.new_page()
                        self._verify_page(page, rec, timeout_sec, headless, on_log)
                    if on_progress:
                        on_progress(rec, idx, total)
                ctx.close()
                log("[BROWSER] Browser session closed.")
        except Exception as e:  # noqa: BLE001
            log(f"[BROWSER DRIVER ERROR] {e}")

    def verify_single(self, rec: LinkRecord, timeout_sec: int = 30, headless: bool = False,
                      keep_browser: bool = False, on_log: Log = None) -> LinkRecord:
        def log(m):
            if on_log:
                on_log(m)
        sanitize_console_title()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            rec.status, rec.error = "Browser error", "Playwright is not installed."
            return rec
        try:
            with sync_playwright() as pw:
                ctx = self._launch(pw, headless)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                self._verify_page(page, rec, timeout_sec, headless, on_log)
                if keep_browser and not headless:
                    log("[BROWSER] Verification finished. Browser stays open 60 s or until you close it.")
                    deadline = time.time() + 60
                    while time.time() < deadline and ctx.pages:
                        time.sleep(1)
                ctx.close()
        except Exception as e:  # noqa: BLE001
            rec.status, rec.error = "Browser error", str(e)
            log(f"[BROWSER SINGLE ERROR] {e}")
        return rec

    def authenticate_session(self, target_url: str = "https://siemens.sharepoint.com", on_log: Log = None) -> bool:
        def log(m):
            if on_log:
                on_log(m)
        sanitize_console_title()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log("[AUTH ERROR] Playwright is not installed.")
            return False
        log(f"[AUTH] Opening browser for one-time authentication to: {target_url}")
        log("[AUTH] Log in with your corporate credentials / MFA. The window closes automatically once authenticated.")
        success = False
        try:
            with sync_playwright() as pw:
                ctx = self._launch(pw, headless=False)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:  # noqa: BLE001
                    log(f"[AUTH NOTE] {e}")
                target_host = target_url.split("/")[2].lower() if "://" in target_url else ""
                deadline = time.time() + 300
                while time.time() < deadline:
                    time.sleep(2.0)
                    if not ctx.pages:
                        log("[AUTH] Browser window was closed by user.")
                        break
                    try:
                        cur, title = page.url, page.title()
                    except Exception:
                        break
                    if not any(k in cur.lower() for k in LOGIN_HOSTS) and "sign in" not in title.lower() and \
                            (target_host and target_host in cur.lower() or "siemens" in cur.lower() or "sharepoint" in cur.lower()):
                        time.sleep(3.0)
                        log(f"[AUTH SUCCESS] Authenticated to: {cur} (Title: {title})")
                        log("[AUTH] Cookies saved — background (headless) batches will reuse this session.")
                        success = True
                        break
                ctx.close()
        except Exception as e:  # noqa: BLE001
            log(f"[AUTH ERROR] {e}")
        return success

    def extract_links(self, url: str, headless: bool = True, timeout_sec: int = 30, on_log: Log = None) -> List[dict]:
        """Render a page (JS + SSO session) and return its anchors: [{'href','text'}]."""
        sanitize_console_title()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return []
        out: List[dict] = []
        try:
            with sync_playwright() as pw:
                ctx = self._launch(pw, headless)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                out = page.eval_on_selector_all(
                    "a[href]", "els => els.map(e => ({href: e.href, text: (e.innerText||e.title||'').trim().slice(0,200)}))")
                ctx.close()
        except Exception as e:  # noqa: BLE001
            if on_log:
                on_log(f"[BROWSER EXTRACT ERROR] {e}")
        return out
