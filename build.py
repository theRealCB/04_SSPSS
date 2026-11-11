#!/usr/bin/env python3
"""Genera la cartella docs/ del sito MkDocs a partire dalle cartelle delle materie.

Non tocca i file originali: copia tutto in docs/, adattando i .md scritti
per Markdown Preview Enhanced (rimuove [TOC] e i blocchi <style>).
Eseguito dalla GitHub Action a ogni push; si può lanciare anche in locale.
"""

import re
import shutil
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
PDF_MANIFEST = ROOT / "pdf_manifest.json"
PDF_TARGETS: list[dict] = []  # pagine per cui generare il PDF in CI se non committato

# Cartelle/file da non pubblicare
EXCLUDE_DIRS = {".git", ".github", "docs", "site", "overrides", "Stage", "__pycache__"}
SKIP_EXT = {".zip", ".html", ".pyc"}          # html MPE: sostituiti dal sito
IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
MATERIAL_EXT = {".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".odt"}

FILE_ICONS = {
    ".pdf": ":material-file-pdf-box:",
    ".docx": ":material-file-word-box:",
    ".doc": ":material-file-word-box:",
    ".pptx": ":material-file-powerpoint-box:",
    ".ppt": ":material-file-powerpoint-box:",
}

# Icona e descrizione per la card in homepage
SUBJECTS = {
    "Adattamento e responsabilità": ("material-account-heart", "Relazione di cura, sensazione e percezione"),
    "Atelier": ("material-arm-flex", "Atelier di fisioterapia"),
    "Anatomia e Fisiologia": ("material-heart-pulse", "Cellula, tessuti, sistema nervoso e apparati"),
    "Comunicazione": ("material-forum", "Sistemi, assiomi e comunicazione umana"),
    "Ergonomia": ("material-chair-rolling", "Colonna vertebrale e movimenti corretti"),
    "Inglese": ("material-translate", "Booklet compilabili e materiale del corso"),
    "Scienze sociali": ("material-account-group", "Etica e sociologia"),
    "Scienze umane e della salute": ("material-hospital-box", "Determinanti della salute e storia sanitaria"),
    "Situazioni di cura": ("material-stethoscope", "Infezioni, igiene e multiresistenze"),
}
DEFAULT_ICON = "material-notebook-outline"


def is_junk(p: Path) -> bool:
    return p.name.startswith("~$") or p.name.startswith(".") or p.suffix.lower() in SKIP_EXT


def page_title(md_path: Path, text: str) -> str:
    """Titolo di pagina: per appunti.md il nome della cartella, altrimenti l'h1."""
    if md_path.stem.lower() in {"appunti", "index"}:
        return md_path.parent.name
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    if m:
        t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if t:
            return t
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if m:
        return m.group(1).strip().title()
    return md_path.stem.replace("_", " ").capitalize()


BLOCK_START = re.compile(r"^\s*([-*+]\s+|\d+\.\s+|>)")


def fix_tight_blocks(text: str) -> str:
    """MPE accetta liste/citazioni attaccate al paragrafo precedente,
    Python-Markdown no: inserisce la riga vuota mancante (fuori dai blocchi di codice)."""
    out, in_fence = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if (not in_fence and out and out[-1].strip()
                and BLOCK_START.match(line) and not BLOCK_START.match(out[-1])
                and not out[-1].lstrip().startswith(("```", "~~~"))):
            out.append("")
        out.append(line)
    return "\n".join(out)


def transform_md(src: Path, title: str, pdf_name: str) -> str:
    text = src.read_text(encoding="utf-8")
    # Via i blocchi <style> di Markdown Preview Enhanced
    text = re.sub(r"<style>.*?</style>\s*", "", text, flags=re.S)
    # Via la riga "# Table of Content" e il segnaposto [TOC] (il tema ha già il sommario)
    text = re.sub(r"^#{1,3}\s*table of content.*$", "", text, flags=re.M | re.I)
    text = re.sub(r"^\[TOC\]\s*$", "", text, flags=re.M)
    text = fix_tight_blocks(text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip() + "\n"

    href = urllib.parse.quote(pdf_name)
    button = f"[:material-file-pdf-box: Scarica il PDF]({href}){{ .md-button }}\n\n"
    return f"---\ntitle: {title}\n---\n\n{button}{text}"


def materials_in(folder: Path, paired_pdfs: set[Path]) -> list[Path]:
    """File scaricabili in folder e nelle sottocartelle senza .md."""
    out = []
    for p in sorted(folder.iterdir()):
        if is_junk(p):
            continue
        if p.is_file() and p.suffix.lower() in MATERIAL_EXT and p not in paired_pdfs:
            out.append(p)
        elif p.is_dir() and not any(c.suffix == ".md" for c in p.rglob("*") if not is_junk(c)):
            out.extend(c for c in sorted(p.rglob("*"))
                       if c.is_file() and not is_junk(c) and c.suffix.lower() in MATERIAL_EXT)
    # Deduplica per nome file (es. booklet presenti sia sciolti sia nella sottocartella)
    seen, unique = set(), []
    for p in out:
        if p.name not in seen:
            seen.add(p.name)
            unique.append(p)
    # Ordinamento naturale (Booklet_2 prima di Booklet_10)
    def natkey(p: Path):
        return [int(t) if t.isdigit() else t.lower()
                for t in re.split(r"(\d+)", p.name)]
    return sorted(unique, key=natkey)


def material_links(folder: Path, dest_folder: Path, paired_pdfs: set[Path]) -> str:
    items = materials_in(folder, paired_pdfs)
    if not items:
        return ""
    lines = ["", "## Materiali", ""]
    for f in items:
        rel = f.relative_to(folder)
        icon = FILE_ICONS.get(f.suffix.lower(), ":material-file-document-outline:")
        href = urllib.parse.quote(str(rel))
        label = f.stem.replace("_", " ")
        lines.append(f"- {icon} [{label}]({href})")
    return "\n".join(lines) + "\n"


def process_folder(src: Path, dest: Path) -> dict:
    """Copia una cartella-materia (o sottocartella) e ritorna info per gli indici."""
    dest.mkdir(parents=True, exist_ok=True)
    mds = [p for p in sorted(src.iterdir()) if p.suffix == ".md" and not is_junk(p)]
    subdirs = [p for p in sorted(src.iterdir()) if p.is_dir() and p.name not in EXCLUDE_DIRS]

    # Copia tutti i file non-md (immagini, pdf, docx, ...)
    for p in src.rglob("*"):
        if p.is_file() and not is_junk(p) and p.suffix != ".md":
            target = dest / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)

    paired = set()
    main_md = next((m for m in mds if m.stem.lower() == "appunti"), mds[0] if mds else None)
    pages = []

    rel = dest.relative_to(DOCS)
    for md in mds:
        text = md.read_text(encoding="utf-8")
        title = page_title(md, text)
        pdf = md.with_suffix(".pdf")
        if pdf.exists():
            paired.add(pdf)
        is_index = md == main_md
        out_name = "index.md" if is_index else md.name
        # href del pulsante, relativo all'URL della pagina (use_directory_urls)
        pdf_href = pdf.name if is_index else f"../{pdf.name}"
        content = transform_md(md, title, pdf_href)
        if is_index:
            content += material_links(src, dest, paired)
        (dest / out_name).write_text(content, encoding="utf-8")
        pages.append((title, out_name))
        if not pdf.exists():
            page_url = f"{rel}/" if is_index else f"{rel}/{md.stem}/"
            PDF_TARGETS.append({"page": page_url, "pdf": f"{rel}/{pdf.name}", "title": title})

    # Sottocartelle con md: ricorsione (es. Scienze sociali/Etica)
    for sub in subdirs:
        if any(c.suffix == ".md" for c in sub.rglob("*") if not is_junk(c)):
            process_folder(sub, dest / sub.name)

    # Nessun md in questa cartella: indice generato
    if not mds:
        md_subdirs = [s for s in subdirs
                      if any(c.suffix == ".md" for c in s.rglob("*") if not is_junk(c))]
        body = ""
        if md_subdirs:
            body += "\n" + "\n".join(
                f"- :material-folder-open: [{s.name}](<{s.name}/index.md>)" for s in md_subdirs) + "\n"
        body += material_links(src, dest, paired)
        if not body.strip():
            body = "\n*Ancora nessun materiale.*\n"
        (dest / "index.md").write_text(
            f"---\ntitle: {src.name}\n---\n\n# {src.name}\n{body}", encoding="utf-8")

    return {"pages": pages}


def main():
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir()

    subjects = [d for d in sorted(ROOT.iterdir())
                if d.is_dir() and d.name not in EXCLUDE_DIRS and not d.name.startswith(".")]

    cards = []
    for d in subjects:
        process_folder(d, DOCS / d.name)
        icon, desc = SUBJECTS.get(d.name, (DEFAULT_ICON, "Appunti e materiali"))
        cards.append(
            f"-   :{icon}:{{ .lg .middle }} __{d.name}__\n\n"
            f"    ---\n\n    {desc}\n\n    [Apri →](<{d.name}/index.md>)"
        )

    cards_md = "\n\n".join(cards)
    (DOCS / "index.md").write_text(
        "---\ntitle: Home\nhide:\n  - navigation\n---\n\n"
        "# Appunti SSPSS\n\n"
        "Moduli complementari SUP · anno 2026/2027. "
        "Scegli una materia: ogni sezione ha gli appunti consultabili online, "
        "il PDF scaricabile e i materiali del corso.\n\n"
        f'<div class="grid cards" markdown>\n\n{cards_md}\n\n</div>\n',
        encoding="utf-8")

    # CSS del sito
    assets = DOCS / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "extra.css").write_text(
        """/* Stile del sito appunti — look "editoriale moderno" sul tema Material */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

/* ------ Palette e tipografia ------ */
:root {
  --md-text-font: "Inter";
  --sspss-red: #B3261E;
  --sspss-red-dark: #8A1A14;
  --sspss-ink: #1C1917;
  --md-primary-fg-color: #B3261E;
  --md-primary-fg-color--light: #D0453B;
  --md-primary-fg-color--dark: #8A1A14;
  --md-primary-bg-color: #FFFFFF;
  --md-accent-fg-color: #D0453B;
  --md-accent-fg-color--transparent: rgba(179, 38, 30, .08);
  --md-typeset-a-color: #A3211A;
  --md-footer-bg-color: #211D1C;
  --md-footer-bg-color--dark: #181514;
  --sspss-th-bg: #FBE9E7;
  --sspss-th-border: rgba(179, 38, 30, .35);
  --sspss-card-shadow: 0 14px 28px rgba(138, 26, 20, .10), 0 2px 6px rgba(28, 25, 23, .06);
  --sspss-header-bg: rgba(255, 255, 255, .82);
  --sspss-hairline: rgba(28, 25, 23, .09);
  --sspss-zebra: rgba(28, 25, 23, .025);
}
[data-md-color-scheme="slate"] {
  --md-hue: 15;                               /* grigio caldo invece del blu di default */
  --md-default-bg-color: hsla(15, 6%, 11%, 1);
  --md-code-bg-color: hsla(15, 6%, 16%, 1);
  --sspss-ink: #EDE7E4;
  --md-accent-fg-color: #FF8A75;
  --md-accent-fg-color--transparent: rgba(255, 138, 117, .12);
  --md-typeset-a-color: #FF9E8E;
  --sspss-th-bg: #352220;
  --sspss-th-border: rgba(255, 138, 117, .4);
  --sspss-card-shadow: 0 14px 28px rgba(0, 0, 0, .35);
  --sspss-header-bg: rgba(26, 23, 22, .85);
  --sspss-hairline: rgba(237, 231, 228, .12);
  --sspss-zebra: rgba(237, 231, 228, .03);
}

/* ------ Barra in alto: chiara, traslucida, con logo rosso ------ */
.md-header {
  background: var(--sspss-header-bg);
  color: var(--md-default-fg-color);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--sspss-hairline);
}
.md-header:not(.md-header--shadow) { transition: none; }
.md-header[data-md-state="shadow"], .md-header--shadow { box-shadow: 0 2px 12px rgba(28,25,23,.06); }
.md-header__button.md-logo { color: var(--sspss-red); }
[data-md-color-scheme="slate"] .md-header__button.md-logo { color: #FF8A75; }
.md-header__title { font-family: "Space Grotesk", sans-serif; font-weight: 600; letter-spacing: -.01em; }
.md-search__form { background: rgba(28, 25, 23, .06); border-radius: 8px; }
[data-md-color-scheme="slate"] .md-search__form { background: rgba(237, 231, 228, .08); }
.md-search__input { color: inherit; }
.md-search__input::placeholder, .md-search__icon { color: var(--md-default-fg-color--light); }
[dir="ltr"] .md-search__form:hover { background: rgba(28, 25, 23, .1); }
[data-md-color-scheme="slate"] [dir="ltr"] .md-search__form:hover { background: rgba(237, 231, 228, .12); }

/* ------ Titoli: Space Grotesk, quasi neri, accento rosso sotto gli h2 ------ */
.md-typeset h1, .md-typeset h2, .md-typeset h3, .md-typeset h4 {
  font-family: "Space Grotesk", sans-serif;
  color: var(--sspss-ink);
  letter-spacing: -.02em;
}
.md-typeset h1 { font-weight: 700; }
.md-typeset h2 { font-weight: 600; }
.md-typeset h3 { font-weight: 600; }
.md-typeset h2::after {
  content: "";
  display: block;
  width: 2rem; height: 3px;
  margin-top: .25rem;
  background: var(--sspss-red);
  border-radius: 2px;
}
[data-md-color-scheme="slate"] .md-typeset h2::after { background: #FF8A75; }
.md-content h1[align="center"] { margin-bottom: .2em; }
.md-content p[align="center"] em {
  color: var(--md-default-fg-color--light);
  font-style: normal;
  font-size: .8em;
  text-transform: uppercase;
  letter-spacing: .14em;
}

/* ------ Contenuto ------ */
.md-content img { max-width: 100%; border-radius: 10px; }
mark { background: #fff59d; padding: 0 .15em; border-radius: 3px; }
[data-md-color-scheme="slate"] mark { background: #8d6e00; color: #fff; }
.md-typeset a { text-underline-offset: 3px; }

/* Pulsante PDF: pillola rossa piena */
.md-typeset .md-button {
  background: var(--sspss-red);
  color: #fff !important;
  border: none;
  border-radius: 999px;
  padding: .5em 1.3em;
  font-weight: 600;
  font-size: .72rem;
  box-shadow: 0 6px 14px rgba(179, 38, 30, .25);
  transition: transform .15s, box-shadow .15s, background .15s;
}
.md-typeset .md-button:hover {
  background: var(--sspss-red-dark);
  color: #fff !important;
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgba(179, 38, 30, .32);
}

/* ------ Menu a sinistra e indice a destra ------ */
.md-nav__title { font-family: "Space Grotesk", sans-serif; letter-spacing: .02em; }
.md-sidebar .md-nav__link { border-radius: 7px; padding: .15rem .45rem; margin: 0 -.45rem; }
.md-sidebar .md-nav__link:hover { background: var(--md-accent-fg-color--transparent); }
.md-nav__link--active, .md-nav__item--active > .md-nav__link { color: var(--md-typeset-a-color); }
.md-sidebar--primary .md-nav__item--active > .md-nav__link--active {
  background: var(--md-accent-fg-color--transparent);
  font-weight: 600;
}
.md-sidebar--secondary .md-nav__link--active { font-weight: 600; }

/* ------ Card della homepage ------ */
.md-typeset .grid.cards > ul > li {
  border: 1px solid var(--sspss-hairline);
  border-radius: 16px;
  padding: 1rem 1.1rem;
  transition: transform .18s, box-shadow .18s, border-color .18s;
}
.md-typeset .grid.cards > ul > li:hover {
  transform: translateY(-3px);
  box-shadow: var(--sspss-card-shadow);
  border-color: rgba(179, 38, 30, .35);
}
.md-typeset .grid.cards > ul > li > hr { margin: .6em 0; border-bottom: 1px solid var(--sspss-hairline); }
.md-typeset .grid.cards > ul > li > p:first-child { display: flex; align-items: center; gap: .6rem; }
.md-typeset .grid.cards > ul > li > p:first-child strong {
  font-family: "Space Grotesk", sans-serif;
  font-size: .78rem;
  letter-spacing: -.01em;
}
.md-typeset .grid.cards .twemoji.lg {
  display: inline-flex;
  padding: .5rem;
  border-radius: 11px;
  background: var(--md-accent-fg-color--transparent);
  color: var(--sspss-red);
}
.md-typeset .grid.cards .twemoji.lg svg { width: 1.35rem; height: 1.35rem; max-height: none; }
[data-md-color-scheme="slate"] .md-typeset .grid.cards .twemoji.lg { color: #FF8A75; }
.md-typeset .grid.cards > ul > li > p:last-child a { font-weight: 600; }

/* ------ Tabelle: angoli morbidi, righe alternate ------ */
.md-typeset table:not([class]) {
  display: table;
  width: 100%;
  border: 1px solid var(--sspss-hairline);
  border-radius: 12px;
  border-collapse: separate;
  border-spacing: 0;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(28, 25, 23, .04);
}
.md-typeset table:not([class]) th {
  background: var(--sspss-th-bg);
  border-bottom: 2px solid var(--sspss-th-border);
  font-family: "Space Grotesk", sans-serif;
  letter-spacing: .01em;
}
.md-typeset table:not([class]) td { border-top: 1px solid var(--sspss-hairline); }
.md-typeset table:not([class]) tbody tr:nth-child(even) { background: var(--sspss-zebra); }
.md-typeset table:not([class]) td,
.md-typeset table:not([class]) th { padding: 7px 12px; }

/* Le liste scorrono attorno alle immagini con float, come in MPE
   (Material le mette in flow-root, che le blocca in colonna accanto al float) */
.md-typeset ol:not([hidden]), .md-typeset ul:not([hidden]) { display: block; }

/* Spaziature compatte come nell'anteprima MPE */
.md-typeset p, .md-typeset li { line-height: 1.6; }
.md-typeset p { margin-top: 0; margin-bottom: .3em; }
.md-typeset h1 { margin-top: 1.5em; margin-bottom: .2em; }
.md-typeset h2 { margin-top: 1.2em; margin-bottom: .2em; }
.md-typeset h3 { margin-top: 1.1em; margin-bottom: .2em; }

/* Menu sinistro e indice destro collassabili (pulsanti creati da extra.js) */
.md-header .sspss-toggle { display: none; }
.sspss-toggle svg { fill: currentColor; }
.sspss-toggle--nav { margin-right: .2rem; }
.sspss-toggle[aria-pressed="false"] { opacity: .55; }
@media screen and (min-width: 76.25em) {
  .md-header .sspss-toggle--nav { display: inline-block; }
  body.sspss-hide-nav .md-sidebar--primary { display: none; }
}
@media screen and (min-width: 60em) {
  .md-header .sspss-toggle--toc { display: inline-block; }
  body.sspss-hide-toc .md-sidebar--secondary { display: none; }
}

@media print {
  .md-typeset .md-button { display: none !important; }  /* niente pulsante PDF dentro il PDF */
  /* titoli mai staccati dal contenuto che segue */
  .md-typeset h1, .md-typeset h2, .md-typeset h3, .md-typeset h4 {
    break-after: avoid; page-break-after: avoid;
  }
  .md-typeset h1 + p, .md-typeset h2 + p,
  .md-typeset h3 + p, .md-typeset h4 + p { break-inside: avoid; }
  /* stampa anche sfondi e colori (evidenziazioni, intestazioni tabelle) */
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
}
""", encoding="utf-8")


    # JS del sito: pulsanti per collassare menu e indice
    (assets / "extra.js").write_text(
        """// Pulsanti nella barra in alto per nascondere/mostrare il menu (sx) e l'indice (dx).
// Lo stato resta salvato nel browser tra una pagina e l'altra.
(function () {
  var ICONS = {
    nav: '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z"/></svg>',
    toc: '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M7 5h14v2H7V5m0 8v-2h14v2H7M4 4.5A1.5 1.5 0 0 1 5.5 6 1.5 1.5 0 0 1 4 7.5 1.5 1.5 0 0 1 2.5 6 1.5 1.5 0 0 1 4 4.5m0 6A1.5 1.5 0 0 1 5.5 12 1.5 1.5 0 0 1 4 13.5 1.5 1.5 0 0 1 2.5 12 1.5 1.5 0 0 1 4 10.5M7 19v-2h14v2H7m-3-2.5A1.5 1.5 0 0 1 5.5 18 1.5 1.5 0 0 1 4 19.5 1.5 1.5 0 0 1 2.5 18 1.5 1.5 0 0 1 4 16.5Z"/></svg>'
  };
  var LABELS = { nav: "menu", toc: "indice" };

  function get(key) { try { return localStorage.getItem("sspss-hide-" + key) === "1"; } catch (e) { return false; } }
  function set(key, v) { try { localStorage.setItem("sspss-hide-" + key, v ? "1" : "0"); } catch (e) {} }

  function apply(key, hidden, btn) {
    document.body.classList.toggle("sspss-hide-" + key, hidden);
    if (btn) {
      btn.setAttribute("aria-pressed", hidden ? "false" : "true");
      btn.title = (hidden ? "Mostra " : "Nascondi ") + LABELS[key];
      btn.setAttribute("aria-label", btn.title);
    }
  }

  function hasSidebar(key) {
    var sel = key === "nav" ? ".md-sidebar--primary" : ".md-sidebar--secondary";
    var el = document.querySelector(sel);
    return el && !el.hidden && el.querySelector(".md-nav__link");
  }

  function makeButton(key) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "md-header__button md-icon sspss-toggle sspss-toggle--" + key;
    btn.innerHTML = ICONS[key];
    btn.addEventListener("click", function () {
      var hidden = !document.body.classList.contains("sspss-hide-" + key);
      set(key, hidden);
      apply(key, hidden, btn);
    });
    apply(key, get(key), btn);
    return btn;
  }

  function init() {
    var header = document.querySelector(".md-header__inner");
    if (!header) return;
    if (hasSidebar("nav")) {
      var title = header.querySelector(".md-header__title");
      header.insertBefore(makeButton("nav"), title);
    }
    if (hasSidebar("toc")) {
      // prima del selettore tema chiaro/scuro
      var palette = header.querySelector(".md-header__option");
      header.insertBefore(makeButton("toc"), palette ? palette : null);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
""", encoding="utf-8")

    # Evita la passata Jekyll di GitHub Pages
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")

    # Elenco dei PDF da generare in CI (pagine senza PDF committato)
    import json
    PDF_MANIFEST.write_text(json.dumps(PDF_TARGETS, ensure_ascii=False, indent=1),
                            encoding="utf-8")

    n_pages = sum(1 for _ in DOCS.rglob("*.md"))
    print(f"docs/ generata: {len(subjects)} materie, {n_pages} pagine md")


if __name__ == "__main__":
    main()
