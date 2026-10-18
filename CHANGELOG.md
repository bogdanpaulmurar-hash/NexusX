# Changelog

## 1.0.0 — 2026-10-18 — NexusX (UCeX v6.7 + ULaE v2.0)
- Unificare UCeX v6.7 (Code Export, Export Manager, Web Recorder) și ULaE v2.0 (Link Checker, SSO, Surse) într-o singură aplicație.
- Nou: Link Map (legături între tool-uri, resurse comune, graf Mermaid), extragerea linkurilor dintr-o pagină, redactare secrete,
  email cu un click pentru orice rezultat (Outlook / SMTP / .eml), icon propriu în taskbar + system tray cu acțiuni rapide.
- Link Checker: parser DOCX complet (antete/subsoluri/note/comentarii, câmpuri HYPERLINK, cross-references REF/PAGEREF,
  TOC, secțiuni), XLSX/PPTX/HTML/MD, verificare HTTP paralelă cu cache și retry, detecție login SSO, ancore, căi locale/UNC.
- Code Export: motor de export unificat, Parte N/M exact, TOC/statistici reale, binare sărite, split JSON corect, ZIP cu toate părțile.
- Migrare automată: perechi Export Manager, catalog surse ULaE, profil Playwright SSO.
- Teste automate (motor + GUI headless).
