# Surse folosite (proveniența fiecărei componente)

Toate sursele provin din Google Drive-ul autorului, folderul **UCeX**
(`https://drive.google.com/drive/folders/1E2TIqokNklRldUZepDsMjiAZGc5ye6Xu`).

| Sursă (Drive) | Versiune | Folosită pentru |
|---|---|---|
| `UCeX/UCeX_v7.py` | UCeX 7.0, 27.08.2026 — confirmat de autor ca versiunea bună | Split & Merge, OneNote Extractor (singurele diferențe funcționale față de 6.7; motorul de export e identic) |
| `UCeX/UCeX_v6_…/UCeX_v6.7.py` (+ `README.md`, `requirements.txt`, `run_UCeX_v6.bat`) | UCeX 6.7, 26.08.2026 | Code Export, Export Manager, Web Recorder, Settings, Log, teme, filtru extensii, split, rezumat folder, perechi implicite (cod comun cu v7) |
| `UCeX/ULaE_…/GPT-5.6 Luna/ULaE_v2.0/` — `app.py`, `models.py`, `extractor.py`, `checker.py`, `exporter.py`, `mail_sender.py`, `sources_manager.py`, `README.md`, `CHANGELOG.md`, `requirements.txt` | ULaE 2.0, 07–08.10.2026 — cea mai nouă versiune ULaE găsită | Link Checker, Browser/SSO (Playwright), rapoarte, email Outlook, Surse SharePoint |
| `UCeX/ULaE_…/GPT-5.6 Luna & Gemini 3.8 Flash/` | — | Folderul indicat ca „ultimele versiuni” apare **gol** prin API-ul Drive; versiunea 2.0 de mai sus (același ansamblu GPT-5.6 Luna & Gemini 3.8 Flash, conform README-ului ei) a fost tratată ca ultima |
| `ClaudeV4.5Haiku/UCeX_v7_0.py` (5 KB), `link checker/link_checker.py` | variante experimentale | neincluse |

## Mapare modul NexusX → sursă

| Modul NexusX | Provine din | Ce e nou |
|---|---|---|
| `codex/constants.py` | UCeX 6.7 `EXT_GROUPS`, `DEFAULT_EXCLUDED`, `DEFAULT_EXPORT_PAIRS`, `detect_lang` | potrivire după nume (Dockerfile…), `.gs`, perechi ULaE/NexusX, căi relative la profil |
| `codex/scanner.py` | UCeX `_scan_thread`, `md5_file`, `count_lines` | scandir, paralelism, binar, .gitignore, stop |
| `codex/exporter.py` | UCeX `_write_export_file`, `_write_export_split`, `_do_export_zip` | motor unic, Parte N/M exact, TOC/Stats reale, JSON split real, ZIP toate părțile, redactare |
| `codex/summary.py` | UCeX `_summary_thread` | imagini/binare implementate, excluderi |
| `codex/redact.py` | — | **nou** |
| `codex/linkmap.py` | — | **nou** (Link Map) |
| `links/models.py` | ULaE `models.py` (`LinkRecord`) | câmpuri secțiune, țintă, timp răspuns, redirect-uri, ocurențe |
| `links/extractor.py` | ULaE `extractor.py` | parser OOXML complet, câmpuri, cross-references, XLSX/PPTX/HTML/MD, mailto/file/UNC |
| `links/checker.py` | ULaE `checker.py` (`http_probe`, `COMMON_BAD_KEYWORDS`) | paralel + cache, retry, login-redirect, soft-404 îmbunătățit, ancore, local/UNC |
| `links/browser.py` | ULaE `checker.py` (`BrowserEngine`) | Edge/Chrome, status HTTP, network-idle, `extract_links` |
| `links/crawler.py` | — | **nou** (linkurile unei pagini) |
| `links/reporter.py` | ULaE `exporter.py` | Excel colorat + Summary, Word tabelar, HTML |
| `links/sources.py` | ULaE `sources_manager.py` | id-uri stabile, rezolvare OneDrive extinsă |
| `mailer.py` | ULaE `mail_sender.py` | SMTP, .eml, email pentru export cod/Link Map, ZIP automat, DE/RO/EN |
| `tools/splitmerge.py` | UCeX 7.0 `_sm_*` (split/merge engine, antet/subsol text) | split pe linii, manifest SHA-256, strip corect, părți lipsă, sortare |
| `tools/onenote.py` | UCeX 7.0 `_on_extract_thread`, `_try_*`, `_extract_text_one` | cititor CAB intern, text UTF-16, imagini decupate, atașamente, Markdown |
| `ui/tab_tools.py` | UCeX 7.0 `_build_tab_split_merge`, `_build_tab_onenote` | integrare cu Code Export, notificări |
| `web/recorder.py` | UCeX `_ws_record_thread`, `_ws_generate_script` | motor separat de UI, script replay cu selectori reali, mascare cookies/tokenuri, screenshot full-page |
| `ui/*` | UCeX (`_build_tab_*`, helperi) + ULaE (`build_*_tab`) | fereastră unică, dispatcher thread-safe, tray, AppUserModelID |
| `assets/*`, `tools/make_icon.py` | — | **nou** (icon) |
