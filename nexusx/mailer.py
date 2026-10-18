# -*- coding: utf-8 -*-
"""
One-click e-mail (ULaE v2.0 mail_sender.py), generalised:

  • Link audit mail: Siemens-styled HTML table + all report files attached (as in ULaE)
  • Code export mail: summary table + export parts / ZIP / Link Map attached (NEW, for UCeX side)
  • Delivery methods, chosen in Settings:
        outlook  – Outlook COM (pywin32): opens the mail for review, or sends directly
        smtp     – any SMTP server with STARTTLS (password from Windows Credential Manager via keyring
                   or asked once per session — never stored in the config file)
        eml      – writes a ready .eml (with attachments) and opens it in the default mail client
    If Outlook is not available it falls back automatically to .eml.
  • Large attachment sets are zipped automatically (threshold configurable).
  • Template language: de (ULaE default) | ro | en.
"""
from __future__ import annotations

import datetime
import html
import mimetypes
import os
import smtplib
import ssl
import subprocess
import sys
import zipfile
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import APP_NAME, APP_VERSION
from .links.models import LinkRecord, status_group

TEXTS = {
    "de": {"hello": "Hallo,", "links_intro": "die Links wurden erfolgreich geprüft. Anbei die Ergebnisse.",
           "code_intro": "anbei der aktuelle Code-Export.", "regards": "Viele Grüße,",
           "total": "Gesamt", "ok": "Erfolgreich", "broken": "Fehlerhaft", "auth": "Auth erforderlich",
           "cols": ["#", "Quelldatei", "Position / Kontext", "Ziel-Link", "Status", "Nachweis / Titel", "Meine Bemerkungen"],
           "files": "Dateien", "parts": "Teile", "attached": "Anhänge"},
    "ro": {"hello": "Bună ziua,", "links_intro": "linkurile au fost verificate. Atașat găsiți rezultatele.",
           "code_intro": "atașat găsiți exportul de cod actual.", "regards": "Cu stimă,",
           "total": "Total", "ok": "Funcționale", "broken": "Defecte", "auth": "Necesită autentificare",
           "cols": ["#", "Fișier sursă", "Poziție / Context", "Link țintă", "Status", "Dovadă / Titlu", "Observații"],
           "files": "Fișiere", "parts": "Părți", "attached": "Atașamente"},
    "en": {"hello": "Hello,", "links_intro": "the links have been checked. Please find the results attached.",
           "code_intro": "please find the current code export attached.", "regards": "Best regards,",
           "total": "Total", "ok": "OK", "broken": "Broken", "auth": "Auth required",
           "cols": ["#", "Source file", "Location / Context", "Target link", "Status", "Evidence / Title", "My remarks"],
           "files": "Files", "parts": "Parts", "attached": "Attachments"},
}

_BADGE = {"ok": ("#107c41", "#e6f4ea"), "broken": ("#a80000", "#fde7e9"), "auth": ("#b05a00", "#fff4ce"),
          "download": ("#005a9e", "#e1effa"), "warn": ("#7a5c00", "#fff8dc"), "pending": ("#605e5c", "#f3f2f1")}


def _wrap(body: str) -> str:
    return ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head>'
            '<body style="font-family:\'Segoe UI\',\'Siemens Sans\',Arial,sans-serif;font-size:14px;color:#212529;'
            f'line-height:1.5;margin:0;padding:15px;">{body}</body></html>')


def build_links_html(records: Sequence[LinkRecord], lang: str = "de", signature: str = "",
                     only_problems: bool = False) -> str:
    t = TEXTS.get(lang, TEXTS["de"])
    e = html.escape
    recs = [r for r in records if not only_problems or status_group(r.status) in ("broken", "auth", "warn")]
    rows = []
    for i, r in enumerate(recs, 1):
        bg = "#ffffff" if i % 2 else "#f8fafc"
        fc, bc = _BADGE.get(status_group(r.status), _BADGE["pending"])
        url = r.url or ""
        shown = e(url[:90] + ("..." if len(url) > 90 else ""))
        rows.append(
            f'<tr style="background-color:{bg};border-bottom:1px solid #e1dfdd;">'
            f'<td style="padding:8px 10px;font-size:13px;text-align:center;color:#605e5c;">{i}</td>'
            f'<td style="padding:8px 10px;font-size:13px;font-weight:600;color:#323130;">{e(r.file or "")}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#605e5c;">{e(r.format_location_display()[:220])}</td>'
            f'<td style="padding:8px 10px;font-size:12px;word-break:break-all;"><a href="{e(url)}" style="color:#006487;text-decoration:none;">{shown}</a></td>'
            f'<td style="padding:8px 10px;font-size:12px;text-align:center;"><span style="display:inline-block;padding:3px 8px;'
            f'border-radius:4px;font-weight:600;color:{fc};background-color:{bc};">{e(r.status or "")}</span></td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#323130;">{e((r.evidence or r.error or "")[:220])}</td>'
            f'<td style="padding:8px 10px;font-size:12px;color:#004b66;font-weight:500;">{e(r.notes or "")}</td></tr>')
    groups = [status_group(r.status) for r in records]
    total, ok = len(records), groups.count("ok") + groups.count("download")
    broken, auth = groups.count("broken"), groups.count("auth")
    head = "".join(f'<th style="padding:10px 8px;font-size:13px;font-weight:600;text-align:left;border-right:1px solid #004f6b;">{c}</th>'
                   for c in t["cols"])
    body = (f'<p style="margin:0 0 16px 0;font-size:15px;">{t["hello"]}<br><br>{t["links_intro"]}</p>'
            '<table style="width:100%;max-width:1100px;margin-bottom:20px;border-collapse:collapse;background-color:#f0f7f9;border-left:4px solid #006487;">'
            f'<tr><td style="padding:8px 14px;font-size:13px;font-weight:bold;color:#004b66;">{t["total"]}: {total} Links | '
            f'<span style="color:#107c41;">✓ {t["ok"]}: {ok}</span> | <span style="color:#a80000;">✗ {t["broken"]}: {broken}</span> | '
            f'<span style="color:#b05a00;">⚠ {t["auth"]}: {auth}</span></td></tr></table>'
            '<table style="width:100%;max-width:1100px;border-collapse:collapse;border:1px solid #d2d0ce;margin-bottom:24px;">'
            f'<thead><tr style="background-color:#006487;color:#ffffff;">{head}</tr></thead><tbody>{"".join(rows)}</tbody></table>'
            f'<p style="margin:20px 0 0 0;font-size:14px;">{t["regards"]}<br>{e(signature or "")}</p>')
    return _wrap(body)


def build_code_html(label: str, parts: Sequence[Path], stats: Dict[str, object], lang: str = "de", signature: str = "") -> str:
    t = TEXTS.get(lang, TEXTS["de"])
    e = html.escape
    rows = "".join(f'<tr><td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;">{e(p.name)}</td>'
                   f'<td style="padding:6px 10px;border-bottom:1px solid #e1dfdd;text-align:right;">{p.stat().st_size / 1024:.1f} KB</td></tr>'
                   for p in parts if p.exists())
    st = "".join(f'<tr><td style="padding:4px 10px;color:#605e5c;">{e(str(k))}</td><td style="padding:4px 10px;font-weight:600;">{e(str(v))}</td></tr>'
                 for k, v in stats.items())
    body = (f'<p style="font-size:15px;">{t["hello"]}<br><br>{t["code_intro"]}</p>'
            f'<h3 style="color:#006487;margin:12px 0 6px;">{e(label)}</h3>'
            f'<table style="border-collapse:collapse;background:#f0f7f9;border-left:4px solid #006487;margin-bottom:14px;">{st}</table>'
            f'<table style="border-collapse:collapse;min-width:420px;border:1px solid #d2d0ce;">'
            f'<tr style="background:#006487;color:#fff;"><th style="padding:8px 10px;text-align:left;">{t["attached"]}</th><th style="padding:8px 10px;">KB</th></tr>{rows}</table>'
            f'<p style="margin-top:20px;">{t["regards"]}<br>{e(signature or "")}</p>'
            f'<p style="font-size:11px;color:#a19f9d;">{APP_NAME} v{APP_VERSION}</p>')
    return _wrap(body)


def maybe_zip(attachments: List[Path], threshold_mb: float, zip_name: str) -> List[Path]:
    total = sum(p.stat().st_size for p in attachments if p.exists())
    if threshold_mb and total > threshold_mb * 1024 * 1024 and len(attachments) > 0:
        zp = attachments[0].parent / zip_name
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in attachments:
                if p.exists():
                    zf.write(p, p.name)
        return [zp]
    return attachments


def _outlook(subject: str, html_body: str, attachments: List[Path], to: str, cc: str, send_direct: bool) -> Tuple[bool, str]:
    try:
        import win32com.client  # type: ignore
    except Exception as e:  # noqa: BLE001
        return False, f"pywin32 not available ({e})"
    try:
        try:  # COM must be initialised in worker threads
            import pythoncom  # type: ignore
            pythoncom.CoInitialize()
        except Exception:
            pass
        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)
        mail.Subject = subject
        if to:
            mail.To = to
        if cc:
            mail.CC = cc
        mail.HTMLBody = html_body
        for a in attachments:
            mail.Attachments.Add(str(Path(a).resolve()))
        if send_direct and to:
            mail.Send()
            return True, f"Email sent via Outlook to {to} ({len(attachments)} attachments)."
        mail.Display(False)
        return True, f"Outlook email opened with {len(attachments)} attachments — review and press Send."
    except Exception as e:  # noqa: BLE001
        return False, f"Could not use Outlook: {e}"


def _message(subject: str, html_body: str, attachments: List[Path], to: str, cc: str, sender: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender or "nexusx@localhost"
    if to:
        msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="nexusx.local")
    msg["X-Unsent"] = "1"  # Outlook opens .eml as an editable draft
    msg.set_content("This message contains an HTML report. Please use an HTML capable mail client.")
    msg.add_alternative(html_body, subtype="html")
    for a in attachments:
        a = Path(a)
        if not a.exists():
            continue
        ctype, _ = mimetypes.guess_type(a.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(a.read_bytes(), maintype=maintype, subtype=subtype, filename=a.name)
    return msg


def _eml(subject: str, html_body: str, attachments: List[Path], to: str, cc: str, out_dir: Path, sender: str) -> Tuple[bool, str]:
    msg = _message(subject, html_body, attachments, to, cc, sender)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"NexusX_Mail_{datetime.datetime.now():%Y%m%d_%H%M%S}.eml"
    p.write_bytes(bytes(msg))
    try:
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except Exception:
        pass
    return True, f"Email draft saved and opened: {p}"


def _smtp(subject: str, html_body: str, attachments: List[Path], to: str, cc: str, cfg: Dict,
          ask_password: Optional[Callable[[str], Optional[str]]]) -> Tuple[bool, str]:
    host, user = cfg.get("smtp_host", ""), cfg.get("smtp_user", "")
    if not host or not to:
        return False, "SMTP host and recipient (To) must be configured in Settings → Email."
    password = None
    try:
        import keyring  # type: ignore
        password = keyring.get_password("NexusX-SMTP", f"{host}:{user}")
    except Exception:
        pass
    if user and not password and ask_password:
        password = ask_password(f"Parola SMTP pentru {user}@{host}")
        if password:
            try:
                import keyring  # type: ignore
                keyring.set_password("NexusX-SMTP", f"{host}:{user}", password)
            except Exception:
                pass
    msg = _message(subject, html_body, attachments, to, cc, cfg.get("smtp_from") or user)
    del msg["X-Unsent"]
    try:
        with smtplib.SMTP(host, int(cfg.get("smtp_port", 587)), timeout=30) as s:
            s.ehlo()
            if cfg.get("smtp_tls", True):
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
            if user and password:
                s.login(user, password)
            s.send_message(msg)
        return True, f"Email sent via SMTP to {to}."
    except Exception as e:  # noqa: BLE001
        return False, f"SMTP error: {e}"


def send_email(subject: str, html_body: str, attachments: List[Path], cfg: Dict, out_dir: Path,
               ask_password: Optional[Callable[[str], Optional[str]]] = None) -> Tuple[bool, str]:
    """Deliver according to cfg['method'] with automatic fallback to .eml."""
    attachments = [Path(a) for a in attachments if Path(a).exists()]
    attachments = maybe_zip(attachments, float(cfg.get("zip_attachments_over_mb", 15) or 0),
                            f"NexusX_Attachments_{datetime.datetime.now():%Y%m%d_%H%M%S}.zip")
    to, cc = cfg.get("to", ""), cfg.get("cc", "")
    method = cfg.get("method", "outlook")
    if method == "smtp":
        return _smtp(subject, html_body, attachments, to, cc, cfg, ask_password)
    if method == "outlook":
        ok, msg = _outlook(subject, html_body, attachments, to, cc, bool(cfg.get("outlook_send_direct")))
        if ok:
            return ok, msg
        ok2, msg2 = _eml(subject, html_body, attachments, to, cc, out_dir, cfg.get("smtp_from", ""))
        return ok2, f"{msg} → fallback: {msg2}"
    return _eml(subject, html_body, attachments, to, cc, out_dir, cfg.get("smtp_from", ""))


def default_signature() -> str:
    try:
        r = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return os.environ.get("USERNAME") or os.environ.get("USER") or "Bogdan Murar"
