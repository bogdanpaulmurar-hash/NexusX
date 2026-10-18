# NexusX — Universal Code & Link eXplorer

<img src="assets/nexusx.png" width="96" align="right" alt="NexusX icon">

**NexusX** este succesorul unificat al **UCeX v7.0** (Universal Code Exporter, incl. Split & Merge și OneNote Extractor) și **ULaE v2.0**
(Universal Link Analyzer & Exporter). Un singur tool desktop care:

1. **exportă tot ce se poate dintr-un cod și din pagini web** – ca să poți stabili legăturile dintre
   tool-urile create prin vibe coding, aplicații, browsere și logările securizate din companie;
2. **verifică linkurile** dintr-un fișier, dintr-o pagină care conține la rândul ei multe linkuri sau dintre
   secțiunile unui document Word (cross-references, cuprins, bookmark-uri) – sunt actuale și funcționale?
3. **trimite rezultatele pe email cu un singur buton**.

Autor: Bogdan Murar

---

## Pornire rapidă (Windows)

```bat
install_deps.bat      :: o singura data — pachete Python + Chromium pentru Playwright
run_NexusX.bat        :: porneste aplicatia (fara consola: dublu-click pe NexusX.pyw)
```

Sau: `python -m nexusx` (opțional `--minimized` → pornește direct în tray).
În **Setări → Creează scurtătură Desktop** obții un `.lnk` cu iconul NexusX; click dreapta → *Pin to taskbar*.

Configurația și log-ul: `%USERPROFILE%\.nexusx\`. La prima pornire sunt preluate automat perechile din
Export Manager-ul UCeX (`ucex_v6_config.json`), catalogul de surse ULaE și sesiunea SSO Playwright
(`.ulae_playwright_profile`) — nu pierzi nimic din ce aveai configurat.

## Taburi

| Tab | Ce face | Origine |
|---|---|---|
| 📦 **Code Export** | Scan folder (Full/Custom), filtru extensii, export `.txt/.md/.html/.json`, split 50/99/custom MB, ZIP, rezumat folder, **Exportă + Email** | UCeX |
| 🚀 **Export Manager** | Perechi sursă → destinație, export în lot, multi-select, reordonare, Link Map pe perechi, email la final | UCeX |
| 🕸 **Link Map** | Harta legăturilor dintre tool-uri: URL-uri, importuri, ProjectReference, căi/UNC, DB, SSO/OAuth, COM (Outlook/Excel/SAP), Selenium/Playwright, Apps Script, env vars, endpoint-uri; dependențe proiect→proiect și resurse comune; export MD/JSON/CSV/HTML (cu graf Mermaid) | **nou** |
| 🔗 **Link Checker** | Extragere din DOCX/PDF/XLSX/PPTX/HTML/MD/TXT, SCAN HTTP paralel, BROWSER VERIFY (headless/vizibil, Edge/Chrome/Chromium), SSO o singură dată, extragere linkuri dintr-o pagină (1–3 niveluri), filtre, editare/observații, rapoarte în 6 formate, **✉ TRIMITE EMAIL** | ULaE |
| 📂 **Surse SharePoint** | Catalog Excel/JSON de documente SharePoint + fișierul local OneDrive, trimitere în Link Checker | ULaE |
| ✂ **Split & Merge** | Împarte orice fișier în părți egale sau de dimensiune fixă (KB/MB/GB) cu antet „FISIER MAMA / PARTE / URMĂTOAREA” pentru text; combină părți/fișiere în ordinea aleasă, cu ștergerea marcajelor, verificare SHA-256 și detectarea părților lipsă | UCeX v7 |
| 📓 **OneNote** | Extrage pachete `.onepkg` (cititor CAB intern → ZIP → cabarchive → expand.exe → 7-Zip) sau secțiuni `.one`: text UTF-16/UTF-8, imagini (și cele lipite în notițe), atașamente, Markdown combinat, raport; „Text extras → Code Export” | UCeX v7 |
| 🌐 **Web Recorder** | Înregistrare sesiune Selenium (HTML, CSS, JS, rețea, cookies, storage, consolă, DOM, formulare, performanță, WebSocket, screenshot, raport master, ZIP, script replay) | UCeX |
| ⚙ **Setări** | Temă (Siemens Petrol / Dark / Light), taburi vizibile, filtru extensii, email, tray, dependențe, scurtătură | UCeX + nou |
| 📋 **Log** | Log live filtrabil, export | UCeX |

### Butonul de email
Configurare în **Setări → Email**:
- **Outlook** (implicit, ca în ULaE): mailul se deschide gata completat (tabel HTML Siemens + toate rapoartele atașate);
  opțional *trimite direct*.
- **SMTP**: server/port/STARTTLS; parola se cere o dată și se păstrează în Windows Credential Manager (`keyring`), niciodată în config.
- **.eml**: fișier gata de trimis, deschis în clientul implicit — funcționează și fără Outlook/pywin32.
Atașamentele mari se arhivează automat (prag configurabil). Template în **de / ro / en**.
Butoane: *✉ TRIMITE EMAIL CU RAPORTUL* (Link Checker), *✉ Exportă + Email* / *Trimite ultimul export* (Code Export),
*Email la final* (Export Manager), *Email Link Map*, **✉ Email rapid** în header și în meniul tray (Ctrl+E).

### Taskbar + tray
Icon propriu în taskbar (AppUserModelID setat → Windows nu mai grupează fereastra sub iconul Python) și în
system tray (`pystray`): Arată/Ascunde, Scan+Export, Export Manager, Verifică linkuri, Link Map, Email, Folder rapoarte, Ieșire;
notificări la finalul task-urilor. Opțiuni: X închide în tray, minimizare în tray.

### Scurtături
`Ctrl+O` folder · `F5` scan · `Ctrl+S` export · `Ctrl+E` email · `Ctrl+L` șterge log

## Ce s-a îmbunătățit (fără a pierde funcții)

**Export cod (UCeX)**
- un singur motor de randare pentru export normal și split (v6.7 avea două copii divergente: în split numerotarea liniilor era forțată, MD5 mereu calculat);
- antet „Parte N/M” exact (v6.7 scria „(estimat…)”), cuprins și în `.md`/`.html` (clicabil), statistici pe extensii (opțiunea „Stats” exista dar nu făcea nimic);
- **redactare secrete** (parole, tokenuri, chei API, connection strings, JWT, credențiale în URL) — sigur de lipit în SiemensGPT/Claude;
- fișierele binare sunt listate dar nu mai umplu exportul cu gunoi; opțiunea „Include binare” (inactivă în v6.7) funcționează;
- Dockerfile/Makefile/requirements.txt sunt recunoscute (v6.7 le lista dar nu le putea potrivi după sufix);
- scanare `os.scandir` + MD5/linii în paralel (UI-ul nu mai îngheață pe foldere mari OneDrive), `.gitignore` opțional;
- split JSON după dimensiunea reală (nu extrapolat din primul fișier), ZIP cu **toate** părțile;
- Rezumat Folder: imagini cu rezoluție și în HTML/JSON, secțiunea „binare” implementată, excluderile respectate.

**Split & Merge și OneNote (UCeX v7)**
- split text pe granițe de linie (v7 putea tăia o linie sau un caracter UTF-8 la mijloc); manifest `.split.json` cu SHA-256;
- merge elimină cu adevărat antetele de split (în v7 regex-ul cerea o linie goală inexistentă, deci antetele rămâneau) — funcționează și pe părți create de v7;
  verificare byte-cu-byte, părți lipsă raportate, „Adaugă toate părțile unui split”, sortare după numărul părții;
- OneNote: cititor CAB intern (nu mai depinde de 7-Zip), text din UTF-16 (unde OneNote ține textul paginilor — v7 citea doar UTF-8),
  imagini decupate din secțiuni, opțiunile „Extrage imagini/atașamente” chiar funcționează, secțiuni `.one` simple acceptate direct.

**Verificare linkuri (ULaE)**
- DOCX citit direct din OOXML: antete, subsoluri, note de subsol/final, comentarii, casete text, controale de conținut (cuprins),
  **câmpuri HYPERLINK**, **cross-reference REF/PAGEREF/NOTEREF**, intrări TOC (`_Toc`), imagini cu link, INCLUDETEXT/LINK, tabele imbricate;
  fiecare link are **secțiunea (§ heading)** în care se află și, pentru linkurile interne, **secțiunea țintă**;
- XLSX, PPTX, `.url`, linkuri `mailto:`, `file://` și UNC (`\\server\share`) — verificate ca existență;
- HTTP în paralel (implicit 8) cu cache pe URL, retry la 429/5xx/timeout, lanț de redirect, timp de răspuns;
- redirect spre login Microsoft/ADFS/OAuth → „Authentication required” (v2.0 raporta OK/Redirect);
- detecție soft-404 mai precisă (fraze puternice vs slabe; mesaje DE/RO SharePoint/Confluence), verificare `#ancoră` pe pagina țintă;
- browser: alegere Edge/Chrome/Chromium (Edge = SSO cu identitatea dispozitivului), cod HTTP al documentului, așteptare network-idle;
- **extragerea tuturor linkurilor dintr-o pagină** (portal/wiki/SharePoint), pe 1–3 niveluri, cu fallback în browserul autentificat;
- rapoarte: Excel colorat pe status + foaie Summary + linkuri clicabile, Word cu tabele per document, HTML filtrabil.

**Legătura dintre cele două** (de ce sunt acum un singur tool)
- URL-urile găsite în cod (Link Map) sau capturate de Web Recorder ajung cu un click în Link Checker;
- Link Map arată ce tool depinde de ce alt tool și ce resurse (SharePoint, share-uri, baze de date, SSO, COM) sunt comune.

## Structura

```
nexusx/
  codex/      scanner, exporter (split), summary, redact, linkmap, constants
  tools/      splitmerge, onenote (din UCeX v7)
  links/      models, extractor, checker, browser (Playwright), crawler, reporter, sources
  web/        recorder (Selenium)
  ui/         app, tab_*, theme, widgets, tray
  mailer.py   Outlook / SMTP / .eml
assets/       nexusx.ico/.png (generat de tools/make_icon.py)
tests/        test_engine.py, test_tools.py, test_ui_smoke.py (GUI headless)
```

Teste: `python -m unittest discover -s tests -v`

Proveniența fiecărei funcții: vezi [SOURCES.md](SOURCES.md).
