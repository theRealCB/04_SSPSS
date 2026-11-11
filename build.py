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
    n_pages_now = sum(1 for _ in DOCS.rglob("*.md"))
    (DOCS / "index.md").write_text(
        "---\ntitle: Home\nhide:\n  - navigation\n  - toc\n---\n\n"
        '<div class="sspss-hero" markdown>\n\n'
        '<p class="sspss-kicker">Moduli complementari SUP &middot; anno 2026/2027</p>\n\n'
        "# Appunti SSPSS\n\n"
        '<p class="sspss-lead">Tutti gli appunti delle lezioni, ordinati per materia: '
        "consultabili online, scaricabili in PDF, con i materiali del corso.</p>\n\n"
        '<div class="sspss-stats">\n'
        f'<span class="sspss-stat"><b>{len(subjects)}</b> materie</span>\n'
        f'<span class="sspss-stat"><b>{n_pages_now}</b> pagine di appunti</span>\n'
        '<span class="sspss-stat"><b>PDF</b> per ogni appunto</span>\n'
        "</div>\n\n"
        "</div>\n\n"
        f'<div class="grid cards" markdown>\n\n{cards_md}\n\n</div>\n',
        encoding="utf-8")

    # CSS del sito
    assets = DOCS / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "extra.css").write_text(
        """/* Stile del sito appunti — app shell moderno sul motore Material */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

/* ------ Design token ------ */
:root {
  --md-text-font: "Inter";
  --sspss-red: #B3261E;
  --sspss-red-dark: #8A1A14;
  --sspss-ink: #1C1917;
  --sspss-surface: #FFFFFF;
  --md-default-bg-color: #F6F2EF;              /* sfondo pagina caldo */
  --md-primary-fg-color: #B3261E;
  --md-primary-fg-color--light: #D0453B;
  --md-primary-fg-color--dark: #8A1A14;
  --md-primary-bg-color: #FFFFFF;
  --md-accent-fg-color: #D0453B;
  --md-accent-fg-color--transparent: rgba(179, 38, 30, .08);
  --md-typeset-a-color: #A3211A;
  --md-code-bg-color: #F3EDE9;
  --sspss-th-bg: #FBE9E7;
  --sspss-th-border: rgba(179, 38, 30, .35);
  --sspss-hairline: rgba(28, 25, 23, .08);
  --sspss-zebra: rgba(28, 25, 23, .025);
  --sspss-shadow-sm: 0 1px 2px rgba(28,25,23,.05), 0 4px 16px rgba(28,25,23,.05);
  --sspss-shadow-lg: 0 16px 32px rgba(138,26,20,.10), 0 2px 8px rgba(28,25,23,.07);
  --sspss-header-bg: rgba(255, 255, 255, .85);
}
[data-md-color-scheme="slate"] {
  --md-hue: 15;
  --sspss-ink: #EDE7E4;
  --sspss-surface: #221D1B;
  --md-default-bg-color: #161211;
  --md-code-bg-color: #2B2422;
  --md-accent-fg-color: #FF8A75;
  --md-accent-fg-color--transparent: rgba(255, 138, 117, .12);
  --md-typeset-a-color: #FF9E8E;
  --sspss-th-bg: #352220;
  --sspss-th-border: rgba(255, 138, 117, .4);
  --sspss-hairline: rgba(237, 231, 228, .1);
  --sspss-zebra: rgba(237, 231, 228, .03);
  --sspss-shadow-sm: 0 1px 2px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.25);
  --sspss-shadow-lg: 0 16px 32px rgba(0,0,0,.45);
  --sspss-header-bg: rgba(34, 29, 27, .85);
}
[data-md-color-scheme="slate"] { --md-default-fg-color: hsla(15, 10%, 92%, .92); }

/* ------ Navbar flottante a pillola ------ */
.md-header {
  background: var(--sspss-header-bg);
  color: var(--md-default-fg-color);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--sspss-hairline);
  border-radius: 999px;
  margin: .65rem auto 0;
  width: min(72rem, calc(100% - 1.6rem));
  box-shadow: var(--sspss-shadow-sm);
}
.md-header[data-md-state="shadow"], .md-header--shadow { box-shadow: var(--sspss-shadow-lg); }
.md-header__inner { padding: .15rem .5rem; }
.md-header__button.md-logo { color: var(--sspss-red); }
[data-md-color-scheme="slate"] .md-header__button.md-logo { color: #FF8A75; }
.md-header__title { font-family: "Space Grotesk", sans-serif; font-weight: 600; letter-spacing: -.01em; }
.md-search__form { background: rgba(28, 25, 23, .06); border-radius: 999px; }
[data-md-color-scheme="slate"] .md-search__form { background: rgba(237, 231, 228, .08); }
.md-search__input { color: inherit; }
.md-search__input::placeholder, .md-search__icon { color: var(--md-default-fg-color--light); }
[dir="ltr"] .md-search__form:hover { background: rgba(28, 25, 23, .1); }
[data-md-color-scheme="slate"] [dir="ltr"] .md-search__form:hover { background: rgba(237, 231, 228, .12); }
@media screen and (min-width: 60em) {
  .md-search__output { border-radius: 16px; margin-top: .4rem; box-shadow: var(--sspss-shadow-lg); }
}

/* ------ Shell: sidebar e contenuto come card ------ */
.md-main__inner { margin-top: 1.1rem; }
.md-sidebar__scrollwrap { margin: 0 .3rem; }
.md-sidebar .md-sidebar__inner > .md-nav {
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 16px;
  padding: .7rem .7rem;
  box-shadow: var(--sspss-shadow-sm);
}
.md-content__inner {
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 20px;
  box-shadow: var(--sspss-shadow-sm);
  padding: 1.4rem 2rem 2.2rem;
  margin-bottom: 1.6rem;
}
.md-content__inner::before { display: none; }
@media screen and (max-width: 44.984375em) {
  .md-content__inner { padding: 1rem 1rem 1.6rem; border-radius: 14px; }
}
/* La homepage respira sul fondo pagina, senza card contenitore */
.md-content__inner:has(.sspss-hero) {
  background: transparent; border: none; box-shadow: none; padding-top: 0;
}

/* ------ Hero homepage ------ */
.sspss-hero { text-align: center; padding: 2.2rem 0 1.4rem; }
.sspss-hero .sspss-kicker {
  display: inline-block;
  font-size: .62rem; font-weight: 600;
  letter-spacing: .12em; text-transform: uppercase;
  color: var(--sspss-red);
  background: var(--md-accent-fg-color--transparent);
  border: 1px solid var(--sspss-th-border);
  border-radius: 999px;
  padding: .3em 1em;
  margin-bottom: .4rem;
}
[data-md-color-scheme="slate"] .sspss-hero .sspss-kicker { color: #FF8A75; }
.sspss-hero h1 {
  font-size: clamp(2.2rem, 5vw, 3rem) !important;
  margin: .2em 0 .25em !important;
}
.sspss-hero .sspss-lead {
  max-width: 34rem; margin: 0 auto;
  font-size: .9rem;
  color: var(--md-default-fg-color--light);
}
.sspss-stats { display: flex; gap: .6rem; justify-content: center; flex-wrap: wrap; margin-top: 1.1rem; }
.sspss-stat {
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 999px;
  box-shadow: var(--sspss-shadow-sm);
  padding: .35em 1em;
  font-size: .7rem;
  color: var(--md-default-fg-color--light);
}
.sspss-stat b { color: var(--sspss-red); font-weight: 700; }
[data-md-color-scheme="slate"] .sspss-stat b { color: #FF8A75; }

/* ------ Titoli ------ */
.md-typeset h1, .md-typeset h2, .md-typeset h3, .md-typeset h4 {
  font-family: "Space Grotesk", sans-serif;
  color: var(--sspss-ink);
  letter-spacing: -.02em;
}
.md-typeset h1 { font-weight: 700; }
.md-typeset h2, .md-typeset h3 { font-weight: 600; }
.md-typeset h2::after {
  content: "";
  display: block;
  width: 2rem; height: 3px;
  margin-top: .25rem;
  background: var(--sspss-red);
  border-radius: 2px;
}
[data-md-color-scheme="slate"] .md-typeset h2::after { background: #FF8A75; }
.sspss-hero h1::after { display: none; }
.md-content h1[align="center"] { margin-bottom: .2em; }
.md-content p[align="center"] em {
  color: var(--md-default-fg-color--light);
  font-style: normal;
  font-size: .8em;
  text-transform: uppercase;
  letter-spacing: .14em;
}

/* ------ Contenuto ------ */
.md-content img { max-width: 100%; border-radius: 12px; }
mark { background: #fff59d; padding: 0 .15em; border-radius: 3px; }
[data-md-color-scheme="slate"] mark { background: #8d6e00; color: #fff; }
.md-typeset a { text-underline-offset: 3px; }
.md-typeset .admonition, .md-typeset details { border-radius: 12px; box-shadow: var(--sspss-shadow-sm); }
.md-typeset code { border-radius: 6px; }

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

/* ------ Navigazione nelle card laterali ------ */
.md-nav__title { font-family: "Space Grotesk", sans-serif; letter-spacing: .02em; background: transparent !important; box-shadow: none !important; }
.md-sidebar .md-nav__link { border-radius: 8px; padding: .22rem .5rem; margin: .05rem 0; }
.md-sidebar .md-nav__link:hover { background: var(--md-accent-fg-color--transparent); }
.md-nav__link--active, .md-nav__item--active > .md-nav__link { color: var(--md-typeset-a-color); }
.md-sidebar--primary .md-nav__item--active > .md-nav__link--active {
  background: var(--md-accent-fg-color--transparent);
  font-weight: 600;
}
.md-sidebar--secondary .md-nav__link--active { font-weight: 600; }

/* ------ Card della homepage ------ */
.md-typeset .grid.cards > ul > li {
  position: relative;
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 18px;
  padding: 1.1rem 1.2rem;
  box-shadow: var(--sspss-shadow-sm);
  transition: transform .18s, box-shadow .18s, border-color .18s;
}
.md-typeset .grid.cards > ul > li:hover {
  transform: translateY(-4px);
  box-shadow: var(--sspss-shadow-lg);
  border-color: rgba(179, 38, 30, .35);
}
.md-typeset .grid.cards > ul > li > hr { display: none; }
.md-typeset .grid.cards > ul > li > p:first-child { display: flex; align-items: center; gap: .6rem; margin-bottom: .45rem; }
.md-typeset .grid.cards > ul > li > p:first-child strong {
  font-family: "Space Grotesk", sans-serif;
  font-size: .8rem;
  letter-spacing: -.01em;
}
.md-typeset .grid.cards .twemoji.lg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.35rem; height: 2.35rem;
  flex: none;
  border-radius: 12px;
  background: var(--md-accent-fg-color--transparent);
  color: var(--sspss-red);
}
.md-typeset .grid.cards .twemoji.lg svg {
  display: block;
  width: 1.35rem; height: 1.35rem;
  max-height: none;
  vertical-align: 0;
}
[data-md-color-scheme="slate"] .md-typeset .grid.cards .twemoji.lg { color: #FF8A75; }
.md-typeset .grid.cards > ul > li > p:last-child a { font-weight: 600; }
/* Tutta la card è cliccabile */
.md-typeset .grid.cards > ul > li > p:last-child a::after { content: ""; position: absolute; inset: 0; }

/* ------ Tabelle ------ */
.md-typeset table:not([class]) {
  display: table;
  width: 100%;
  border: 1px solid var(--sspss-hairline);
  border-radius: 12px;
  border-collapse: separate;
  border-spacing: 0;
  overflow: hidden;
  box-shadow: var(--sspss-shadow-sm);
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

/* ------ Footer leggero ------ */
.md-footer { background: transparent; color: var(--md-default-fg-color); }
.md-footer__inner { padding: 0 .8rem 1.4rem; }
.md-footer__link {
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 14px;
  box-shadow: var(--sspss-shadow-sm);
  padding: .5rem .9rem;
  color: var(--md-default-fg-color);
  transition: transform .15s, box-shadow .15s;
}
.md-footer__link:hover { opacity: 1; transform: translateY(-2px); box-shadow: var(--sspss-shadow-lg); }
.md-footer__title, .md-footer__direction { color: inherit; }
.md-footer-meta { background: transparent; }

/* Le liste scorrono attorno alle immagini con float, come in MPE
   (Material le mette in flow-root, che le blocca in colonna accanto al float) */
.md-typeset ol:not([hidden]), .md-typeset ul:not([hidden]) { display: block; }

/* Spaziature compatte come nell'anteprima MPE */
.md-typeset p, .md-typeset li { line-height: 1.6; }
.md-typeset p { margin-top: 0; margin-bottom: .3em; }
.md-typeset h1 { margin-top: 1.5em; margin-bottom: .2em; }
.md-typeset h2 { margin-top: 1.2em; margin-bottom: .2em; }
.md-typeset h3 { margin-top: 1.1em; margin-bottom: .2em; }
.md-typeset h1:first-child, .md-typeset .md-button + h1 { margin-top: .2em; }

/* Menu sinistro collassabile (pulsante in header creato da extra.js) */
.md-header .sspss-toggle { display: none; }
.sspss-toggle svg { fill: currentColor; }
.sspss-toggle--nav { margin-right: .2rem; }
.sspss-toggle[aria-pressed="false"] { opacity: .55; }
@media screen and (min-width: 76.25em) {
  .md-header .sspss-toggle--nav { display: inline-block; }
  body.sspss-hide-nav .md-sidebar--primary { display: none; }
}

/* Indice a destra: card a tendina con freccia accanto al titolo */
.sspss-toc-title { display: flex; align-items: center; cursor: pointer; user-select: none; }
.sspss-toc-arrow {
  margin-left: auto;
  display: inline-flex;
  padding: .1rem;
  background: none; border: none; cursor: pointer;
  border-radius: 6px;
  color: var(--md-default-fg-color--light);
}
.sspss-toc-title:hover .sspss-toc-arrow {
  background: var(--md-accent-fg-color--transparent);
  color: var(--md-typeset-a-color);
}
.sspss-toc-arrow svg { fill: currentColor; transition: transform .2s; }
body.sspss-hide-toc .sspss-toc-arrow svg { transform: rotate(-90deg); }
@media screen and (min-width: 60em) {
  body.sspss-hide-toc .md-sidebar--secondary .md-nav--secondary > .md-nav__list { display: none; }
}

@media print {
  .md-typeset .md-button { display: none !important; }  /* niente pulsante PDF dentro il PDF */
  .md-content__inner { background: #fff; border: none; box-shadow: none; padding: 0; }
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
        """// Barra in alto: pulsante per il menu a sinistra. Indice a destra: freccia dropdown sulla card.
// Lo stato resta salvato nel browser tra una pagina e l'altra.
(function () {
  var NAV_ICON = '<svg viewBox="0 0 24 24" width="24" height="24"><path d="M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2Z"/></svg>';
  var CHEVRON = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M7.41 8.58 12 13.17l4.59-4.59L18 10l-6 6-6-6 1.41-1.42Z"/></svg>';

  function get(key) { try { return localStorage.getItem("sspss-hide-" + key) === "1"; } catch (e) { return false; } }
  function set(key, v) { try { localStorage.setItem("sspss-hide-" + key, v ? "1" : "0"); } catch (e) {} }

  function applyNav(hidden, btn) {
    document.body.classList.toggle("sspss-hide-nav", hidden);
    btn.setAttribute("aria-pressed", hidden ? "false" : "true");
    btn.title = (hidden ? "Mostra" : "Nascondi") + " menu";
    btn.setAttribute("aria-label", btn.title);
  }

  function initNav(header) {
    var sidebar = document.querySelector(".md-sidebar--primary");
    if (!sidebar || sidebar.hidden || !sidebar.querySelector(".md-nav__link")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "md-header__button md-icon sspss-toggle sspss-toggle--nav";
    btn.innerHTML = NAV_ICON;
    btn.addEventListener("click", function () {
      var hidden = !document.body.classList.contains("sspss-hide-nav");
      set("nav", hidden); applyNav(hidden, btn);
    });
    applyNav(get("nav"), btn);
    header.insertBefore(btn, header.querySelector(".md-header__title"));
  }

  function applyToc(hidden, btn) {
    document.body.classList.toggle("sspss-hide-toc", hidden);
    btn.setAttribute("aria-expanded", hidden ? "false" : "true");
    btn.title = (hidden ? "Mostra" : "Nascondi") + " indice";
    btn.setAttribute("aria-label", btn.title);
  }

  function initToc() {
    var title = document.querySelector(".md-sidebar--secondary .md-nav--secondary > .md-nav__title");
    if (!title || !document.querySelector(".md-sidebar--secondary .md-nav__link")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sspss-toc-arrow";
    btn.innerHTML = CHEVRON;
    title.appendChild(btn);
    title.classList.add("sspss-toc-title");
    title.addEventListener("click", function (e) {
      e.preventDefault();
      var hidden = !document.body.classList.contains("sspss-hide-toc");
      set("toc", hidden); applyToc(hidden, btn);
    });
    applyToc(get("toc"), btn);
  }

  function init() {
    var header = document.querySelector(".md-header__inner");
    if (header) initNav(header);
    initToc();
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
