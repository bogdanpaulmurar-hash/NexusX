# Changelog

## Nelansat — Link Checker: autentificare SSO / MFA
- Browserul vizibil așteaptă acum până la 180 s confirmarea MFA de pe alt dispozitiv; înainte renunța după ~20 s.
  Logarea rămâne ca în ULaE v2.0 (profil persistent + 🔑 SSO LOGIN o dată).
- Pornire fără fereastră cmd: `NexusX.vbs` (acceptă `--minimized`).
- Butonul X trimite aplicația în tray în mod implicit (și pentru configurațiile existente); ieșire din meniul tray.

## 1.1.0 — 2026-10-18 — funcțiile UCeX v7.0
- Tab nou ✂ Split & Merge (din UCeX v7): split egal/fix KB-MB-GB, antete pentru text, merge cu ordine manuală.
  Corectat: split text pe granițe de linie, merge care chiar elimină antetele (bug v7), manifest + verificare SHA-256, părți lipsă.
- Tab nou 📓 OneNote (din UCeX v7): .onepkg/.one → text, imagini, atașamente, raport. Nou: cititor CAB intern, text UTF-16,
  imagini decupate din secțiuni, Markdown combinat, trimitere în Code Export.

## 1.0.0 — 2026-10-18 — NexusX (UCeX v6.7 + ULaE v2.0)
- Unificare UCeX v6.7 (Code Export, Export Manager, Web Recorder) și ULaE v2.0 (Link Checker, SSO, Surse) într-o singură aplicație.
- Nou: Link Map (legături între tool-uri, resurse comune, graf Mermaid), extragerea linkurilor dintr-o pagină, redactare secrete,
  email cu un click pentru orice rezultat (Outlook / SMTP / .eml), icon propriu în taskbar + system tray cu acțiuni rapide.
- Link Checker: parser DOCX complet (antete/subsoluri/note/comentarii, câmpuri HYPERLINK, cross-references REF/PAGEREF,
  TOC, secțiuni), XLSX/PPTX/HTML/MD, verificare HTTP paralelă cu cache și retry, detecție login SSO, ancore, căi locale/UNC.
- Code Export: motor de export unificat, Parte N/M exact, TOC/statistici reale, binare sărite, split JSON corect, ZIP cu toate părțile.
- Migrare automată: perechi Export Manager, catalog surse ULaE, profil Playwright SSO.
- Teste automate (motor + GUI headless).
