# NexusX — note pentru Claude

Succesorul unificat al UCeX v7 (export de cod și pagini web, Split & Merge, OneNote Extractor) și ULaE v2 (verificare de linkuri). Aplicație desktop Python cu tray și trimitere de rezultate pe e-mail.

## Comenzi
- Instalare dependențe: `install_deps.bat` (apoi `python -m playwright install chromium`)
- Pornire: `run_NexusX.bat` sau `NexusX.pyw` (fără consolă) / `python -m nexusx`
- Teste: `python -m unittest discover -s tests` (`tests/fake_tk.py` înlocuiește Tkinter, deci rulează și fără ecran)
- Versiune: `APP_VERSION` în `nexusx/__init__.py` + intrare în `CHANGELOG.md`

## Hartă (`nexusx/`)
- `codex/` — exportul de cod: `scanner`, `exporter`, `linkmap` (legăturile dintre tool-uri), `redact` (ascunde date sensibile), `summary`
- `links/` — verificarea linkurilor: `extractor`, `crawler`, `checker`, `browser` (Playwright/SSO), `reporter`, `sources`
- `tools/` — `splitmerge.py`, `onenote.py` (aduse din UCeX v7)
- `ui/` — un tab per funcție (`tab_code`, `tab_web`, `tab_links`, `tab_linkmap`, `tab_tools`, `tab_settings`), `tray.py`, `theme.py`
- `mailer.py` (SMTP / Outlook, parola în keyring), `config.py`, `paths.py`, `logbus.py`
- `SOURCES.md` — de unde vine fiecare funcție din UCeX/ULaE

## Reguli
- Toate funcțiile din UCeX v7 și ULaE v2 trebuie păstrate; versiunile vechi sunt în folderul Google Drive „UCeX”, ca referință.
- Fără `.exe`: Python pornit cu `pythonw`, icon propriu în taskbar și tray.
- Certificatele firmei prin `truststore`; parolele doar în keyring, niciodată în config sau log.
- Repo-ul a fost redenumit din `UCeX-_-ULeX` în `NexusX`.
- Commit-uri în engleză; README și răspunsurile către utilizator în română.
- Documentație și UI vizibile: fără numele angajatorului, e-mailuri de firmă, ID-uri sau numere interne (au fost scoase pe 18.10 — nu le reintroduce).

## Context comun
Prezentarea proiectelor și lista de erori/modificări sunt în două Google Docs: **PROIECTE_CONTEXT (live)** și **MODIFICARI_PROIECTE (live)** — citește doar secțiunea NexusX. Ce s-a implementat și confirmat se șterge din MODIFICARI.

## Când se actualizează fișierul
În același commit, când se schimbă comenzile de instalare/pornire/test, structura pachetului sau când un defect scoate la iveală o regulă de ținut minte. Nu pentru funcții obișnuite. Sub ~60 de rânduri.
