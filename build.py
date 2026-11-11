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
        """/* Stile del sito appunti */
.md-content h1[align="center"] { margin-bottom: .2em; }
.md-content p[align="center"] em { color: var(--md-default-fg-color--light); }
.md-content img { max-width: 100%; border-radius: 4px; }
mark { background: #fff59d; padding: 0 .15em; border-radius: 2px; }
[data-md-color-scheme="slate"] mark { background: #8d6e00; color: #fff; }
.md-typeset .grid.cards > ul > li { border-radius: 8px; }
@media print {
  .md-typeset .md-button { display: none !important; }  /* niente pulsante PDF dentro il PDF */
}
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
