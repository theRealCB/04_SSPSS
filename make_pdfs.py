#!/usr/bin/env python3
"""Genera i PDF mancanti stampando le pagine del sito già costruito (site/).

Va eseguito DOPO `python build.py` e `mkdocs build`.
Se nella cartella della materia è committato un PDF con lo stesso nome del .md
(es. l'export da Markdown Preview Enhanced), quello ha la precedenza e
non viene toccato.
"""

import functools
import http.server
import json
import threading
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
PORT = 8137

FOOTER = """<div style="font-size:8px; width:100%; text-align:center; color:#888;">
pagina <span class="pageNumber"></span> di <span class="totalPages"></span></div>"""
EMPTY = "<div></div>"


def main():
    targets = json.loads((ROOT / "pdf_manifest.json").read_text(encoding="utf-8"))
    todo = [t for t in targets if not (SITE / t["pdf"]).exists()]
    if not todo:
        print("Nessun PDF da generare.")
        return

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1100, "height": 1400})
        for t in todo:
            url = f"http://127.0.0.1:{PORT}/" + urllib.parse.quote(t["page"])
            try:
                page.goto(url, wait_until="load", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass  # CDN lente (Mermaid/font) non bloccano la stampa
            time.sleep(1.0)
            out = SITE / t["pdf"]
            out.parent.mkdir(parents=True, exist_ok=True)
            page.pdf(
                path=str(out),
                format="A4",
                margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"},
                display_header_footer=True,
                header_template=EMPTY,
                footer_template=FOOTER,
                print_background=True,
            )
            print(f"PDF generato: {t['pdf']}")
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
