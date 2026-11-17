#!/usr/bin/env python3
"""Genera i PDF mancanti stampando le pagine del sito già costruito (site/).

Va eseguito DOPO `python build.py` e `mkdocs build`.
Se nella cartella della materia è committato un PDF con lo stesso nome del .md
(es. l'export da Markdown Preview Enhanced), quello ha la precedenza e
non viene toccato.
"""

import functools
import http.server
import io
import json
import re
import threading
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
PORT = 8137

FOOTER = """<div style="font-size:8px; width:100%; text-align:center; color:#888;">
pagina <span class="pageNumber"></span> di <span class="totalPages"></span></div>"""
EMPTY = "<div></div>"
PDF_OPTS = dict(
    format="A4",
    margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"},
    display_header_footer=True,
    header_template=EMPTY,
    footer_template=FOOTER,
    print_background=True,
)
END_MARK = "SSPSSFINEINDICE"

# Inserisce l'indice dopo la copertina: due livelli di titoli, numeri da riempire
ADD_TOC = """(mark) => {
  const root = document.querySelector('.md-content__inner');
  const cover = root && root.querySelector('.sspss-cover');
  if (!cover) return [];
  const hs = [...root.querySelectorAll('h1,h2,h3,h4')].filter(h =>
    !h.closest('.sspss-cover') && h.getAttribute('align') !== 'center');
  if (hs.length < 2) return [];
  const top = Math.min(...hs.map(h => +h.tagName[1]));
  const pick = hs.filter(h => +h.tagName[1] <= top + 1);
  const text = h => { const c = h.cloneNode(true);
    c.querySelectorAll('.headerlink').forEach(x => x.remove());
    return c.textContent.replace(/\\s+/g, ' ').trim(); };
  const box = document.createElement('div');
  box.className = 'sspss-printtoc';
  box.innerHTML = '<p class="sspss-printtoc__title">Indice</p>';
  const ol = document.createElement('ol');
  pick.forEach((h, i) => {
    const li = document.createElement('li');
    const row = document.createElement('div');
    row.className = 'sspss-printtoc__row sspss-printtoc__row--' + (+h.tagName[1] - top + 1);
    const t = document.createElement('span'); t.textContent = text(h);
    const d = document.createElement('span'); d.className = 'sspss-printtoc__dots';
    const n = document.createElement('span'); n.className = 'sspss-printtoc__num'; n.textContent = '00';
    row.append(t, d, n); li.append(row); ol.append(li);
  });
  box.append(ol);
  const end = document.createElement('span');
  end.className = 'sspss-printtoc__end'; end.textContent = mark;
  ol.lastChild.firstChild.append(end);
  cover.after(box);
  return pick.map(text);
}"""

FILL_TOC = """(nums) => {
  document.querySelectorAll('.sspss-printtoc__num').forEach((n, i) => { n.textContent = nums[i] || ''; });
  document.querySelectorAll('.sspss-printtoc__end').forEach(x => x.remove());
}"""


def norm(t: str) -> str:
    return re.sub(r"[^0-9a-zàèéìòù]", "", t.lower())


def toc_pages(pdf: bytes, titles: list[str]) -> list[str]:
    """Pagina (1-based) di ogni titolo, cercata dopo l'indice e in ordine."""
    pages = [norm(p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages]
    mark = norm(END_MARK)
    start = next((i + 1 for i, p in enumerate(pages) if mark in p), 1)
    out, cur = [], start
    for t in titles:
        key = norm(t)
        hit = next((i for i in range(cur, len(pages)) if key and key in pages[i]), None)
        if hit is None:
            out.append("")
            continue
        cur = hit
        out.append(str(hit + 1))
    return out


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
            titles = page.evaluate(ADD_TOC, END_MARK)
            if titles:
                # prima stampa di prova per sapere dove cade ogni capitolo
                page.evaluate(FILL_TOC, toc_pages(page.pdf(**PDF_OPTS), titles))
            page.pdf(path=str(out), **PDF_OPTS)
            print(f"PDF generato: {t['pdf']}")
        browser.close()
    srv.shutdown()


if __name__ == "__main__":
    main()
