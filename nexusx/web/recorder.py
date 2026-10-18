# -*- coding: utf-8 -*-
"""
Web Recorder (UCeX v6.7 _ws_record_thread) as a GUI-independent engine.

Same capture set (HTML, CSS, JS, Network/CDP, screenshot, cookies, storage, console,
DOM map, meta, links, forms, performance, WebSocket, interaction timeline, master report,
ZIP, generated script) — improved:
  • the generated replay script uses real selectors (id → name → CSS → link text) instead of
    commented placeholders, and replays typed values (passwords are never written)
  • cookie values and storage tokens are masked in the saved files by default (corporate SSO)
  • links.json can be pushed straight into the Link Checker
  • full-page screenshot on Chrome/Edge via CDP when available
"""
from __future__ import annotations

import base64
import datetime
import json
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .. import APP_NAME, APP_VERSION
from ..codex.redact import MASK

EXTRACT_KEYS = ["html", "css", "js", "net", "snap", "cookies", "storage", "console", "dom",
                "meta", "links", "forms", "perf", "ws", "script"]

EXTRACT_LABELS = [
    ("html", "HTML complet", "Salveaza sursa HTML completa"),
    ("css", "CSS inline+extern", "Extrage toate stilurile CSS"),
    ("js", "JavaScript", "Extrage scripturile JS"),
    ("net", "Network/HAR", "Inregistreaza request-urile de retea"),
    ("snap", "Screenshot", "Captura ecran (full page pe Chrome/Edge)"),
    ("cookies", "Cookies", "Salveaza cookies sesiunii (valori mascate)"),
    ("storage", "LocalStorage", "Salveaza localStorage/sessionStorage"),
    ("console", "Console log", "Captureaza mesajele din consola"),
    ("dom", "DOM complet", "Salveaza harta elementelor interactive"),
    ("meta", "Meta tags", "Extrage toate meta tag-urile"),
    ("links", "Linkuri", "Listeaza toate link-urile paginii (→ Link Checker)"),
    ("forms", "Formulare", "Mapeaza toate formularele"),
    ("perf", "Performance", "Metrici de performanta"),
    ("ws", "WebSocket", "Intercepteaza mesaje WebSocket"),
    ("script", "Script Python", "Genereaza script Selenium de replay"),
]

TRACKER_JS = r"""
if (!window.__ucex_tracking) {
  window.__ucex_tracking = true; window.__ucex_events = []; window.__ucex_console = []; window.__ucex_ws_msgs = [];
  function sel(el){
    if(!el||!el.tagName) return {};
    var css = el.tagName.toLowerCase();
    if (el.id) css = '#'+CSS.escape(el.id);
    else if (el.name) css = el.tagName.toLowerCase()+'[name="'+el.name+'"]';
    else if (el.className && typeof el.className==='string') css = el.tagName.toLowerCase()+'.'+el.className.trim().split(/\s+/).slice(0,2).map(CSS.escape).join('.');
    return {tag:el.tagName, id:el.id||'', name:el.name||'', css:css, type:el.type||'',
            text:(el.innerText||el.value||'').substring(0,80), href:el.href||''};
  }
  document.addEventListener('click', function(e){var s=sel(e.target);s.type_evt='click';s.url=location.href;window.__ucex_events.push(Object.assign({type:'click'},s));}, true);
  document.addEventListener('change', function(e){var el=e.target;var s=sel(el);
     var v=(el.type==='password')?'':(el.value||'').substring(0,120);
     window.__ucex_events.push(Object.assign({type:'input', value:v, secret:el.type==='password', url:location.href}, s));}, true);
  document.addEventListener('submit', function(e){var s=sel(e.target);window.__ucex_events.push(Object.assign({type:'submit', action:e.target.action||'', url:location.href}, s));}, true);
  document.addEventListener('keydown', function(e){ if(e.key==='Enter'||e.key==='Escape'){window.__ucex_events.push(Object.assign({type:'keydown', key:e.key, url:location.href}, sel(e.target)));}}, true);
  var _st=null; window.addEventListener('scroll', function(){clearTimeout(_st);_st=setTimeout(function(){window.__ucex_events.push({type:'scroll',x:scrollX,y:scrollY,url:location.href});},300);}, true);
  var _f=window.fetch; if(_f){window.fetch=function(){var a=arguments;window.__ucex_events.push({type:'fetch',url:(typeof a[0]==='string'?a[0]:(a[0]&&a[0].url)||''),method:(a[1]&&a[1].method)||'GET',page:location.href});return _f.apply(this,a);};}
  var _x=XMLHttpRequest.prototype.open; XMLHttpRequest.prototype.open=function(m,u){window.__ucex_events.push({type:'xhr',method:m,url:u,page:location.href});return _x.apply(this,arguments);};
  var _W=window.WebSocket; if(_W){window.WebSocket=function(u,p){var ws=new _W(u,p);ws.addEventListener('message',function(e){window.__ucex_ws_msgs.push({url:u,data:(''+e.data).substring(0,500),time:new Date().toISOString()});});window.__ucex_events.push({type:'websocket_open',url:u,page:location.href});return ws;};}
  ['log','warn','error','info'].forEach(function(l){var o=console[l];console[l]=function(){window.__ucex_console.push({level:l,msg:Array.prototype.slice.call(arguments).join(' ').substring(0,300),time:new Date().toISOString()});o.apply(console,arguments);};});
}
"""

Callback = Optional[Callable[..., None]]


class WebRecorder:
    def __init__(self, url: str, browser: str, headless: bool, out_dir: Path, opts: Dict[str, bool],
                 delay: float = 0.5, mask_secrets: bool = True,
                 on_log: Callback = None, on_event: Callback = None, on_progress: Callback = None,
                 on_done: Callback = None):
        self.url, self.browser, self.headless = url, browser, headless
        self.out_dir, self.opts, self.delay = Path(out_dir), opts, max(0.1, float(delay or 0.5))
        self.mask_secrets = mask_secrets
        self.on_log, self.on_event, self.on_progress, self.on_done = on_log, on_event, on_progress, on_done
        self.running = False
        self.paused = False
        self.events: List[Dict] = []
        self.har: List[Dict] = []
        self.links: List[Dict] = []
        self.session_dir: Optional[Path] = None
        self._thread: Optional[threading.Thread] = None

    # ── control ──
    def start(self) -> None:
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        return self.paused

    def stop(self) -> None:
        self.running = False
        self.paused = False

    # ── helpers ──
    def _log(self, msg: str, tag: str = "info"):
        if self.on_log:
            self.on_log(msg, tag)

    def _prog(self, pct: float, label: str):
        if self.on_progress:
            self.on_progress(pct, label)

    def _event(self, evt: Dict):
        evt.setdefault("time", datetime.datetime.now().strftime("%H:%M:%S"))
        self.events.append(evt)
        if self.on_event:
            self.on_event(evt)

    def _driver(self):
        from selenium import webdriver as wd
        b = self.browser
        if b == "Chrome":
            from selenium.webdriver.chrome.options import Options
            o = Options()
            o.add_argument("--start-maximized")
            o.add_argument("--disable-blink-features=AutomationControlled")
            o.add_experimental_option("excludeSwitches", ["enable-automation"])
            o.add_experimental_option("useAutomationExtension", False)
            if self.headless:
                o.add_argument("--headless=new")
            o.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
            try:  # Selenium ≥4.6 ships Selenium Manager (no webdriver-manager download needed)
                return wd.Chrome(options=o)
            except Exception:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager
                return wd.Chrome(service=Service(ChromeDriverManager().install()), options=o)
        if b == "Edge":
            from selenium.webdriver.edge.options import Options
            o = Options()
            o.add_argument("--start-maximized")
            if self.headless:
                o.add_argument("--headless=new")
            o.set_capability("ms:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
            try:
                return wd.Edge(options=o)
            except Exception:
                from selenium.webdriver.edge.service import Service
                from webdriver_manager.microsoft import EdgeChromiumDriverManager
                return wd.Edge(service=Service(EdgeChromiumDriverManager().install()), options=o)
        from selenium.webdriver.firefox.options import Options
        o = Options()
        if self.headless:
            o.add_argument("--headless")
        try:
            return wd.Firefox(options=o)
        except Exception:
            from selenium.webdriver.firefox.service import Service
            from webdriver_manager.firefox import GeckoDriverManager
            return wd.Firefox(service=Service(GeckoDriverManager().install()), options=o)

    # ── main loop ──
    def _run(self) -> None:
        try:
            import selenium  # noqa: F401
        except ImportError as e:
            self._log(f"EROARE import: {e}. Apasa 'Instaleaza dependinte'!", "error")
            self.running = False
            if self.on_done:
                self.on_done(None)
            return
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._log("=" * 50, "title")
        self._log(f" {APP_NAME} Web Recorder v{APP_VERSION} — {self.browser}", "title")
        self._log(f" URL: {self.url}", "title")
        self._log("=" * 50, "title")
        driver = None
        chromium = self.browser in ("Chrome", "Edge")
        try:
            driver = self._driver()
            if chromium:
                try:
                    for cmd in ("Network.enable", "Page.enable", "Runtime.enable"):
                        driver.execute_cdp_cmd(cmd, {})
                    self._log("DevTools CDP activat.", "ok")
                except Exception as e:  # noqa: BLE001
                    self._log(f"CDP: {e}", "warn")
            driver.get(self.url)
            self._log(f"Pagina incarcata: {self.url}", "ok")
            self._event({"type": "navigate", "element": "page", "value": self.url, "url": self.url})
            try:
                driver.execute_script(TRACKER_JS)
                self._log("Event tracker JS injectat.", "ok")
            except Exception as e:  # noqa: BLE001
                self._log(f"JS inject: {e}", "warn")

            last_url = self.url
            while self.running:
                if self.paused:
                    time.sleep(0.3)
                    continue
                try:
                    cur = driver.current_url
                    if cur != last_url:
                        last_url = cur
                        self._log(f"Navigare: {cur}")
                        self._event({"type": "navigate", "element": "page", "value": cur, "url": cur})
                    try:
                        driver.execute_script(TRACKER_JS)  # idempotent; re-inject after navigation
                    except Exception:
                        pass
                    try:
                        evts = driver.execute_script("var e=window.__ucex_events||[];window.__ucex_events=[];return e;") or []
                        for ev in evts:
                            tag, eid = ev.get("tag", ""), ev.get("id", "")
                            ev["element"] = f"<{tag}#{eid}>" if eid else (f"<{tag}>" if tag else ev.get("type", ""))
                            ev["value"] = ev.get("text") or ev.get("value") or ev.get("url", "")
                            ev["url"] = ev.get("url") or ev.get("page", "")
                            self._event(ev)
                    except Exception:
                        pass
                    if chromium and self.opts.get("net"):
                        try:
                            for entry in driver.get_log("performance"):
                                msg = json.loads(entry.get("message", "{}")).get("message", {})
                                method = msg.get("method", "")
                                if method in ("Network.responseReceived", "Network.requestWillBeSent"):
                                    params = msg.get("params", {})
                                    req = params.get("request") or params.get("response") or {}
                                    if req.get("url"):
                                        self.har.append({"method": method, "url": req.get("url"),
                                                         "status": (params.get("response") or {}).get("status"),
                                                         "type": params.get("type", ""), "time": entry.get("timestamp", 0)})
                        except Exception:
                            pass
                except Exception as e:  # noqa: BLE001
                    self._log(f"Browser inchis: {e}", "warn")
                    break
                time.sleep(self.delay)
            self._save(driver, chromium)
        except Exception as e:  # noqa: BLE001
            self._log(f"EROARE: {e}", "error")
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.running = False
            self._log("══ Sesiune incheiata ══", "title")
            if self.on_done:
                self.on_done(self.session_dir)

    # ── artefacts ──
    def _js(self, driver, code: str, default=None):
        try:
            return driver.execute_script(code)
        except Exception:
            return default

    def _save(self, driver, chromium: bool) -> None:
        o = self.opts
        self._log("Salvare artefacte...")
        self._prog(10, "Salvare artefacte...")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        sd = self.out_dir / f"session_{ts}"
        sd.mkdir(parents=True, exist_ok=True)
        self.session_dir = sd
        rep = [f"# {APP_NAME} v{APP_VERSION} — Web Analysis Report\n",
               f"**URL:** {self.url}  \n**Browser:** {self.browser}  \n**Date:** {ts}\n\n---\n"]

        def save_json(name, data):
            (sd / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        steps = [k for k in EXTRACT_KEYS if o.get(k)]
        for i, key in enumerate(steps, 1):
            self._prog(10 + 80 * i / max(1, len(steps)), f"{key}…")
            try:
                if key == "html":
                    (sd / "page_source.html").write_text(driver.page_source, encoding="utf-8")
                    rep.append("## HTML\nSalvat in `page_source.html`\n\n")
                elif key == "snap":
                    saved = False
                    if chromium:
                        try:
                            m = driver.execute_cdp_cmd("Page.getLayoutMetrics", {})
                            cs = m.get("cssContentSize") or m.get("contentSize") or {}
                            shot = driver.execute_cdp_cmd("Page.captureScreenshot", {
                                "format": "png", "captureBeyondViewport": True,
                                "clip": {"x": 0, "y": 0, "width": cs.get("width", 1366), "height": min(cs.get("height", 900), 16000), "scale": 1}})
                            (sd / "screenshot_fullpage.png").write_bytes(base64.b64decode(shot["data"]))
                            saved = True
                        except Exception:
                            pass
                    driver.save_screenshot(str(sd / "screenshot.png"))
                    rep.append("## Screenshot\n`screenshot.png`" + (" + `screenshot_fullpage.png`" if saved else "") + "\n\n")
                elif key == "css":
                    data = self._js(driver, """var s=[];for(var i=0;i<document.styleSheets.length;i++){try{var ss=document.styleSheets[i];
                      var r=ss.cssRules||ss.rules,t='';for(var j=0;j<r.length;j++){t+=r[j].cssText+'\\n';}s.push({href:ss.href||'inline',css:t});}
                      catch(e){s.push({href:(document.styleSheets[i].href||'blocked'),css:'/* cross-origin: not readable */'});}}return s;""", [])
                    (sd / "styles.css").write_text("".join(f"/* === {x.get('href','')} === */\n{x.get('css','')}\n\n" for x in data or []), encoding="utf-8")
                    rep.append(f"## CSS\n{len(data or [])} stylesheets — `styles.css`\n\n")
                elif key == "js":
                    data = self._js(driver, """var s=[];document.querySelectorAll('script').forEach(function(t){s.push({src:t.src||'inline',content:t.innerHTML.substring(0,80000)});});return s;""", [])
                    (sd / "scripts.js").write_text("".join(f"// === {x.get('src','')} ===\n{x.get('content','')}\n\n" for x in data or []), encoding="utf-8")
                    rep.append(f"## JavaScript\n{len(data or [])} scripts — `scripts.js`\n\n")
                elif key == "meta":
                    data = self._js(driver, """var m=[];document.querySelectorAll('meta').forEach(function(t){m.push({name:t.name||t.getAttribute('property')||t.getAttribute('http-equiv')||'',content:(t.content||'').substring(0,300)});});return m;""", [])
                    save_json("meta_tags.json", data or [])
                    if data:
                        rep.append("## Meta Tags\n| Name | Content |\n|---|---|\n" + "".join(f"| `{m.get('name','')}` | {m.get('content','')[:80]} |\n" for m in data[:30]) + "\n")
                elif key == "links":
                    data = self._js(driver, """var l=[];var t=document.querySelectorAll('a[href]');for(var i=0;i<t.length&&i<2000;i++){l.push({text:(t[i].innerText||t[i].title||'').trim().substring(0,80),href:t[i].href||''});}return l;""", [])
                    self.links = data or []
                    save_json("links.json", self.links)
                    rep.append(f"## Linkuri\n{len(self.links)} linkuri — `links.json` (trimise in Link Checker la cerere)\n\n")
                elif key == "forms":
                    data = self._js(driver, """var f=[];document.querySelectorAll('form').forEach(function(fm){var fl=[];fm.querySelectorAll('input,select,textarea,button').forEach(function(x){fl.push({tag:x.tagName,type:x.type||'',name:x.name||'',id:x.id||'',placeholder:(x.placeholder||'').substring(0,60)});});f.push({id:fm.id||'',action:fm.action||'',method:fm.method||'',fields:fl});});return f;""", [])
                    save_json("forms.json", data or [])
                    rep.append(f"## Formulare\n{len(data or [])} formulare — `forms.json`\n\n")
                elif key == "cookies":
                    cookies = driver.get_cookies()
                    if self.mask_secrets:
                        cookies = [dict(c, value=MASK if c.get("value") else "") for c in cookies]
                    save_json("cookies.json", cookies)
                    rep.append(f"## Cookies\n{len(cookies)} cookies — `cookies.json`" + (" (valori mascate)" if self.mask_secrets else "") + "\n\n")
                elif key == "storage":
                    data = self._js(driver, """var ls={},ss={};try{for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);ls[k]=(localStorage.getItem(k)||'').substring(0,500);}}catch(e){}
                      try{for(var j=0;j<sessionStorage.length;j++){var q=sessionStorage.key(j);ss[q]=(sessionStorage.getItem(q)||'').substring(0,500);}}catch(e){}return {localStorage:ls,sessionStorage:ss};""", {})
                    if self.mask_secrets and data:
                        for bucket in data.values():
                            for k in list(bucket):
                                if any(s in k.lower() for s in ("token", "auth", "secret", "msal", "session", "credential", "key")):
                                    bucket[k] = MASK
                    save_json("storage.json", data or {})
                    rep.append("## Storage\n`storage.json`\n\n")
                elif key == "perf":
                    data = self._js(driver, """try{var t=performance.timing;return {domContentLoaded:t.domContentLoadedEventEnd-t.navigationStart,loadComplete:t.loadEventEnd-t.navigationStart,
                      ttfb:t.responseStart-t.navigationStart,domInteractive:t.domInteractive-t.navigationStart,
                      resources:performance.getEntriesByType('resource').slice(0,150).map(function(r){return {name:r.name.substring(0,160),type:r.initiatorType,duration:Math.round(r.duration),size:r.transferSize||0};})};}catch(e){return {error:e.toString()};}""", {})
                    save_json("performance.json", data or {})
                    if data and "error" not in data:
                        rep.append("## Performance\n| Metric | Value |\n|---|---|\n"
                                   f"| TTFB | {data.get('ttfb', 0)} ms |\n| DOM Interactive | {data.get('domInteractive', 0)} ms |\n"
                                   f"| DOM Content Loaded | {data.get('domContentLoaded', 0)} ms |\n| Load Complete | {data.get('loadComplete', 0)} ms |\n"
                                   f"| Resources | {len(data.get('resources', []))} |\n\n")
                elif key == "console":
                    cons = self._js(driver, "var c=window.__ucex_console||[];window.__ucex_console=[];return c;", []) or []
                    if chromium:
                        try:
                            cons += [{"level": b.get("level", ""), "msg": b.get("message", ""), "time": b.get("timestamp", "")}
                                     for b in driver.get_log("browser")]
                        except Exception:
                            pass
                    save_json("console_log.json", cons)
                    rep.append(f"## Console Log\n{len(cons)} mesaje — `console_log.json`\n\n")
                elif key == "dom":
                    data = self._js(driver, """var o=[];var n=document.querySelectorAll('a,button,input,select,textarea,[onclick],[role=button],form,h1,h2,h3,nav,header,footer,main,iframe');
                      for(var i=0;i<n.length&&i<1500;i++){var e=n[i];o.push({tag:e.tagName,id:e.id||'',name:e.name||'',type:e.type||'',role:e.getAttribute('role')||'',
                      text:(e.innerText||e.value||'').substring(0,80),href:e.href||e.src||'',class:(typeof e.className==='string'?e.className:'').substring(0,60)});}return o;""", [])
                    save_json("dom_map.json", data or [])
                    rep.append(f"## DOM Map\n{len(data or [])} elemente interactive — `dom_map.json`\n\n")
                elif key == "net" and self.har:
                    save_json("network_log.json", self.har)
                    rep.append(f"## Network Requests\n{len(self.har)} requests — `network_log.json`\n\n### Top 20\n| Method | Status | URL |\n|---|---|---|\n"
                               + "".join(f"| {r.get('method','').replace('Network.','')} | {r.get('status') or ''} | {r.get('url','')[:100]} |\n" for r in self.har[:20]) + "\n")
                elif key == "ws":
                    msgs = self._js(driver, "return window.__ucex_ws_msgs||[];", []) or []
                    if msgs:
                        save_json("websocket_msgs.json", msgs)
                        rep.append(f"## WebSocket Messages\n{len(msgs)} mesaje — `websocket_msgs.json`\n\n")
                elif key == "script":
                    self._generate_script(sd)
                    rep.append("## Replay script\n`interaction_script.py` (Selenium, selectori reali)\n\n")
                self._log(f"✅ {key} salvat", "ok")
            except Exception as e:  # noqa: BLE001
                self._log(f"⚠️ {key}: {e}", "warn")

        if self.events:
            save_json("events.json", self.events)
            rep.append(f"## Interactiuni\n{len(self.events)} evenimente — `events.json`\n\n### Timeline\n| Time | Type | Element | Value | URL |\n|---|---|---|---|---|\n")
            for ev in self.events[:80]:
                rep.append(f"| {ev.get('time','')} | {ev.get('type','')} | {ev.get('element','')} | {str(ev.get('value',''))[:40]} | {str(ev.get('url',''))[:60]} |\n")
        (sd / "web_analysis_report.md").write_text("".join(rep), encoding="utf-8")
        zp = self.out_dir / f"session_{ts}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in sd.rglob("*"):
                if fp.is_file():
                    zf.write(fp, fp.relative_to(self.out_dir))
        self._log(f"✅ Raport master + ZIP: {zp}", "ok")
        self._prog(100, "✅ Complet")

    def _generate_script(self, sd: Path) -> None:
        lines = ["#!/usr/bin/env python3", f'"""Replay script generated by {APP_NAME} v{APP_VERSION} Web Recorder — {self.url}"""',
                 "import time", "from selenium import webdriver", "from selenium.webdriver.common.by import By",
                 "from selenium.webdriver.support import expected_conditions as EC",
                 "from selenium.webdriver.support.ui import WebDriverWait", "",
                 f"driver = webdriver.{ 'Edge' if self.browser == 'Edge' else ('Firefox' if self.browser == 'Firefox' else 'Chrome') }()",
                 "wait = WebDriverWait(driver, 15)", "",
                 "def el(by, value):", "    return wait.until(EC.element_to_be_clickable((by, value)))", "",
                 f"driver.get({self.url!r})", "time.sleep(2)", ""]

        def locator(ev: Dict) -> str:
            if ev.get("id"):
                return f"By.ID, {ev['id']!r}"
            if ev.get("name"):
                return f"By.NAME, {ev['name']!r}"
            if ev.get("tag", "").upper() == "A" and ev.get("text"):
                return f"By.PARTIAL_LINK_TEXT, {ev['text'][:40].strip()!r}"
            if ev.get("css"):
                return f"By.CSS_SELECTOR, {ev['css']!r}"
            return ""

        last_nav = self.url
        for ev in self.events:
            t = ev.get("type")
            if t == "navigate" and ev.get("value") and ev.get("value") != last_nav:
                last_nav = ev["value"]
                lines += [f"# navigated to {last_nav}", f"# driver.get({last_nav!r})  # (uncomment if the click above does not navigate)", ""]
            elif t == "click":
                loc = locator(ev)
                lines.append(f"el({loc}).click()  # {str(ev.get('text',''))[:40]!r}" if loc else f"# click on {ev.get('element')} (no stable selector)")
                lines.append("time.sleep(0.5)")
            elif t == "input":
                loc = locator(ev)
                if ev.get("secret"):
                    lines.append(f"# password field {loc} — value intentionally not recorded")
                elif loc:
                    lines += [f"_e = el({loc})", "_e.clear()", f"_e.send_keys({str(ev.get('value',''))!r})"]
            elif t == "submit":
                loc = locator(ev)
                if loc:
                    lines.append(f"el({loc}).submit()")
            elif t in ("fetch", "xhr"):
                lines.append(f"# {t.upper()}: {ev.get('method','')} {str(ev.get('url',''))[:120]}")
        lines += ["", "input('Replay finished — press Enter to close the browser…')", "driver.quit()"]
        (sd / "interaction_script.py").write_text("\n".join(lines), encoding="utf-8")
