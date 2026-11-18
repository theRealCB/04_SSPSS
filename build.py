#!/usr/bin/env python3
"""Genera la cartella docs/ del sito MkDocs a partire dalle cartelle delle materie.

Non tocca i file originali: copia tutto in docs/, adattando i .md scritti
per Markdown Preview Enhanced (rimuove [TOC] e i blocchi <style>).
Eseguito dalla GitHub Action a ogni push; si può lanciare anche in locale.
"""

import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
PDF_MANIFEST = ROOT / "pdf_manifest.json"
PDF_TARGETS: list[dict] = []  # pagine per cui generare il PDF in CI se non committato
DOWNLOADS: list[dict] = []    # file per il centro download: materia -> gruppo -> file

# Cartelle/file da non pubblicare
EXCLUDE_DIRS = {".git", ".github", "docs", "site", "overrides", "Stage", "__pycache__", "scripts", "gh"}
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
    "Atelier": ("material-arm-flex", "Atelier di fisioterapia ed ergoterapia"),
    "Atelier/Fisioterapia": ("material-arm-flex", "Evidenze, dolore e primo intervento"),
    "Atelier/Ergoterapia": ("material-human-child", "Fasi della vita e sviluppo del bambino"),
    "Anatomia e Fisiologia": ("material-heart-pulse", "Cellula, tessuti, sistema nervoso e apparati"),
    "Comunicazione": ("material-forum", "Sistemi, assiomi e comunicazione umana"),
    "Ergonomia": ("material-chair-rolling", "Colonna vertebrale e movimenti corretti"),
    "Inglese": ("material-translate", "Booklet compilabili e materiale del corso"),
    "Scienze sociali": ("material-account-group", "Etica e sociologia"),
    "Scienze umane e della salute": ("material-hospital-box", "Determinanti della salute e storia sanitaria"),
    "Situazioni di cura": ("material-stethoscope", "Infezioni, igiene e multiresistenze"),
    # Sotto-materie
    "Etica": ("material-scale-balance", "La morale sociale e l'etica professionale"),
    "Sociologia": ("material-account-group", "Esperimenti e dinamiche sociali"),
}
DEFAULT_ICON = "material-notebook-outline"


def subject_meta(name: str, parent: str = "") -> tuple:
    """Icona e descrizione: prima la chiave 'Materia/Sotto-materia', poi il nome."""
    return SUBJECTS.get(f"{parent}/{name}", SUBJECTS.get(name, (DEFAULT_ICON, "Appunti e materiali")))


# Più appunti nella stessa cartella (appunti_fisio.md, appunti_ergo.md, ...):
# ognuno diventa una sotto-materia, come se avesse una sua sottocartella.
STAGE = Path(tempfile.mkdtemp(prefix="sspss_split_"))
ORIGIN: dict[Path, Path] = {}          # file in STAGE -> file vero nella repo
SPLIT_RE = re.compile(r"^appunti[_-](.+)$", re.I)
REL_LINK = re.compile(r'(\]\(<?|(?:src|href)=")(?!https?:|mailto:|/|#|\.\./|data:)')


def split_notes(src: Path, mds: list[Path]) -> tuple[list[Path], set[Path]]:
    """Ritorna (sottocartelle virtuali, file della cartella già usati)."""
    parts = [m for m in mds if SPLIT_RE.match(m.stem)]
    if len(parts) < 2 or any(m.stem.lower() == "appunti" for m in mds):
        return [], set()
    virtual, used = [], set()
    for md in parts:
        key = SPLIT_RE.match(md.stem).group(1)
        text = md.read_text(encoding="utf-8")
        m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
        name = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else key
        name = re.sub(rf"^{re.escape(src.name)}\W*", "", name, flags=re.I).strip() or key
        name = name[0].upper() + name[1:]
        folder = STAGE / src.relative_to(ROOT) / name
        folder.mkdir(parents=True, exist_ok=True)
        # i link relativi (immagini, allegati) puntano alla cartella vera, un livello sopra
        (folder / "appunti.md").write_text(REL_LINK.sub(r"\1../", text), encoding="utf-8")
        ORIGIN[folder / "appunti.md"] = md
        used.add(md)
        for extra, target in ((f"quiz_{key}.json", "quiz.json"), (f"glossario_{key}.md", "glossario.md")):
            f = src / extra
            if f.exists():
                shutil.copy2(f, folder / target)
                ORIGIN[folder / target] = f
                used.add(f)
        virtual.append(folder)
    return virtual, used


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


def demote_headings(text: str) -> str:
    """MPE usa più h1 come sezioni; Material vuole un solo h1 per pagina
    (il template dell'indice mostra solo i figli del primo h1).
    Con 2+ h1 markdown declassa tutti i titoli di un livello."""
    lines = text.split("\n")
    h1 = 0
    in_fence = False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        elif not in_fence and re.match(r"^#\s", line):
            h1 += 1
    if h1 < 2:
        return text
    out, in_fence = [], False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        m = re.match(r"^(#{1,5})(\s)", line) if not in_fence else None
        if m:
            line = "#" + line
        out.append(line)
    return "\n".join(out)


MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def updated_on(src: Path) -> str:
    """Data dell'ultima modifica (ultimo commit, altrimenti data del file)."""
    src = ORIGIN.get(src, src)
    ts = last_commit_ts(src) or int(src.stat().st_mtime)
    d = time.localtime(ts)
    return f"{d.tm_mday} {MESI[d.tm_mon - 1]} {d.tm_year}"


def transform_md(src: Path, title: str, pdf_name: str, crumb: str = "",
                 subject: str = "", quiz_href: str | None = None,
                 gloss_href: str | None = None) -> str:
    text = src.read_text(encoding="utf-8")
    # Via i blocchi <style> di Markdown Preview Enhanced
    text = re.sub(r"<style>.*?</style>\s*", "", text, flags=re.S)
    # Via la riga "# Table of Content" e il segnaposto [TOC] (il tema ha già il sommario)
    text = re.sub(r"^#{1,3}\s*table of content.*$", "", text, flags=re.M | re.I)
    text = re.sub(r"^\[TOC\]\s*$", "", text, flags=re.M)
    # salti pagina prima del primo capitolo: nel PDF ci pensano copertina e indice
    first = re.search(r"^#{1,6}\s", text, re.M)
    if first:
        head = re.sub(r'^<div style="page-break-[^"]*"></div>\s*$', "", text[:first.start()], flags=re.M)
        text = head + text[first.start():]
    text = fix_tight_blocks(text)
    text = demote_headings(text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip() + "\n"

    when = updated_on(src)
    # Copertina: visibile solo in stampa, quindi solo nel PDF
    cover = ('<div class="sspss-cover">'
             '<p class="sspss-cover__kicker">Appunti SSPSS &middot; Moduli complementari SUP</p>'
             f'<p class="sspss-cover__title">{title}</p>'
             + (f'<p class="sspss-cover__sub">{subject}</p>' if subject and subject != title else "")
             + f'<p class="sspss-cover__meta">Anno 2026/2027 &middot; aggiornato il {when}</p>'
             "</div>\n\n")
    href = urllib.parse.quote(pdf_name)
    button = f"[:material-file-pdf-box: Scarica il PDF]({href}){{ .md-button }}\n"
    if quiz_href:
        button += f"[:material-head-question: Fai il quiz]({quiz_href}){{ .md-button .sspss-quizlink }}\n"
    if gloss_href:
        button += f"[:material-book-alphabet: Glossario]({gloss_href}){{ .md-button .sspss-glosslink }}\n"
    button += "\n"
    footer = f'\n<p class="sspss-updated">Ultimo aggiornamento: {when}</p>\n'
    return f"---\ntitle: {title}\n---\n\n{cover}{crumb}{button}{text}{footer}"




def breadcrumb(rel_parts: tuple, current: str, is_index: bool) -> str:
    """Briciole di pane sopra il titolo: Home / Materia / Pagina."""
    depth = len(rel_parts) if is_index else len(rel_parts) + 1
    ancestors = rel_parts[:-1] if is_index else rel_parts
    items = [f'<a href="{"../" * depth}">Home</a>']
    for j, part in enumerate(ancestors):
        items.append(f'<a href="{"../" * (depth - 1 - j)}">{part}</a>')
    items.append(f"<span>{current}</span>")
    sep = '<span class="sspss-crumb__sep">/</span>'
    return '<nav class="sspss-crumb">' + sep.join(items) + "</nav>\n\n"


def last_commit_ts(path: Path) -> int:
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%ct", "--", str(path)],
                           capture_output=True, text=True, cwd=ROOT)
        return int(r.stdout.strip() or 0)
    except Exception:
        return 0

def natkey(p: Path):
    """Ordinamento naturale (Booklet_2 prima di Booklet_10)."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", p.name)]


def materials_in(folder: Path, paired_pdfs: set[Path]) -> list[tuple]:
    """File scaricabili raggruppati: (None, file sciolti), poi una voce per
    ogni sottocartella senza .md. Deduplica per nome tra i gruppi."""
    groups, seen = [], set()

    def add(name, files):
        unique = [f for f in sorted(files, key=natkey) if f.name not in seen]
        seen.update(f.name for f in unique)
        if unique:
            groups.append((name, unique))

    add(None, [p for p in folder.iterdir()
               if p.is_file() and not is_junk(p)
               and p.suffix.lower() in MATERIAL_EXT and p not in paired_pdfs])
    for p in sorted(folder.iterdir()):
        if (p.is_dir() and not is_junk(p)
                and not any(c.suffix == ".md" for c in p.rglob("*") if not is_junk(c))):
            add(p.name, [c for c in p.rglob("*")
                         if c.is_file() and not is_junk(c) and c.suffix.lower() in MATERIAL_EXT])
    return groups


def material_links(folder: Path, dest_folder: Path, paired_pdfs: set[Path]) -> str:
    groups = materials_in(folder, paired_pdfs)
    if not groups:
        return ""
    rel = dest_folder.relative_to(DOCS)
    for gname, files in groups:
        for f in files:
            frel = f.relative_to(folder)
            DOWNLOADS.append({
                "subject": rel.parts[0],
                "sub": rel.parts[1] if len(rel.parts) > 1 else None,
                "folder": gname.replace("_", " ") if gname else None,
                "label": f.stem.replace("_", " "),
                "ext": f.suffix.lower().lstrip("."),
                "url": "/".join(urllib.parse.quote(x) for x in (*rel.parts, *frel.parts)),
            })
    lines = ["", '<div class="sspss-materials" markdown>',
             '<p class="sspss-materials__title">Materiali</p>', ""]
    for gname, files in groups:
        if gname:
            lines += [f'<p class="sspss-materials__group">{gname.replace("_", " ")}</p>', ""]
        for f in files:
            rel = f.relative_to(folder)
            icon = FILE_ICONS.get(f.suffix.lower(), ":material-file-document-outline:")
            href = urllib.parse.quote(str(rel))
            label = f.stem.replace("_", " ")
            lines.append(f"- {icon} [{label}]({href})")
        lines.append("")
    lines.append("</div>")
    return "\n".join(lines) + "\n"


def process_folder(src: Path, dest: Path) -> dict:
    """Copia una cartella-materia (o sottocartella) e ritorna info per gli indici."""
    dest.mkdir(parents=True, exist_ok=True)
    mds = [p for p in sorted(src.iterdir()) if p.suffix == ".md" and not is_junk(p)]
    subdirs = [p for p in sorted(src.iterdir()) if p.is_dir() and p.name not in EXCLUDE_DIRS]
    virtual, used = split_notes(src, mds) if ROOT in src.parents else ([], set())
    mds = [m for m in mds if m not in used]
    subdirs = sorted(subdirs + virtual, key=lambda p: p.name.lower())

    # Copia tutti i file non-md (immagini, pdf, docx, ...)
    for p in src.rglob("*"):
        if p.is_file() and not is_junk(p) and p.suffix != ".md" and p not in used:
            target = dest / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)

    paired = set()
    notes = [m for m in mds if m.stem.lower() != "glossario"]
    has_gloss = len(notes) != len(mds)
    main_md = next((m for m in notes if m.stem.lower() == "appunti"),
                   notes[0] if notes else (mds[0] if mds else None))
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
        current = rel.parts[-1] if is_index else title
        is_gloss = md.stem.lower() == "glossario"
        has_quiz = (src / "quiz.json").exists() and not is_gloss
        quiz_href = ("quiz/" if is_index else "../quiz/") if has_quiz else None
        gloss_href = (("glossario/" if is_index else "../glossario/")
                      if has_gloss and not is_gloss else None)
        content = transform_md(md, title, pdf_href, breadcrumb(rel.parts, current, is_index),
                               subject=" · ".join(rel.parts), quiz_href=quiz_href,
                               gloss_href=gloss_href)
        if is_index:
            content += material_links(src, dest, paired)
        (dest / out_name).write_text(content, encoding="utf-8")
        pages.append((title, out_name))
        if not pdf.exists():
            page_url = f"{rel}/" if is_index else f"{rel}/{md.stem}/"
            PDF_TARGETS.append({"page": page_url, "pdf": f"{rel}/{pdf.name}", "title": title})
        DOWNLOADS.append({
            "subject": rel.parts[0],
            "sub": rel.parts[1] if len(rel.parts) > 1 else None,
            "folder": None,
            "label": "Glossario" if is_gloss else f"{title} — appunti",
            "ext": "pdf",
            "url": "/".join(urllib.parse.quote(x) for x in (*rel.parts, pdf.name)),
        })

    # Pagina del quiz (se la cartella ha un quiz.json)
    if mds and (src / "quiz.json").exists():
        name = rel.parts[-1]
        (dest / "quiz.md").write_text(
            f"---\ntitle: Quiz — {name}\nhide:\n  - toc\n---\n\n"
            + breadcrumb(rel.parts, "Quiz", False)
            + f"# Quiz — {name}\n\n"
            '<div class="sspss-quiz" data-src="../quiz.json" data-back="../"></div>\n',
            encoding="utf-8")

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
            sub_cards = []
            for sub2 in md_subdirs:
                icon, desc = subject_meta(sub2.name, src.name)
                sub_cards.append(
                    f"-   :{icon}:{{ .lg .middle }} __{sub2.name}__\n\n"
                    f"    ---\n\n    {desc}\n\n    [Apri →](<{sub2.name}/index.md>)"
                )
            body += ('\n<div class="grid cards" markdown>\n\n'
                     + "\n\n".join(sub_cards) + "\n\n</div>\n")
        body += material_links(src, dest, paired)
        if not body.strip():
            body = "\n*Ancora nessun materiale.*\n"
        crumb = breadcrumb(rel.parts, rel.parts[-1], True)
        (dest / "index.md").write_text(
            f"---\ntitle: {src.name}\n---\n\n{crumb}# {src.name}\n{body}", encoding="utf-8")

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
        ts = last_commit_ts(d)
        badge = ('<span class="sspss-badge-new">Aggiornato</span>'
                 if ts and time.time() - ts < 14 * 86400 else "")
        cards.append(
            f"-   :{icon}:{{ .lg .middle }} __{d.name}__{badge}\n\n"
            f"    ---\n\n    {desc}\n\n    [Apri →](<{d.name}/index.md>)"
            f'<span class="sspss-views" hidden></span>'
        )

    cards_md = "\n\n".join(cards)
    n_pages_now = sum(1 for p in DOCS.rglob("*.md") if p.name not in ("quiz.md", "glossario.md"))
    (DOCS / "index.md").write_text(
        "---\ntitle: Home\nhide:\n  - navigation\n  - toc\n---\n\n"
        '[:material-folder-download: Centro download](download/){ .md-button .sspss-dlbtn }\n\n'
        '<div class="sspss-hero" markdown>\n\n'
        '<p class="sspss-kicker">Moduli complementari SUP &middot; anno 2026/2027</p>\n\n'
        "# Appunti SSPSS\n\n"
        '<p class="sspss-lead">Tutti gli appunti delle lezioni, ordinati per materia: '
        "consultabili online, scaricabili in PDF, con i materiali del corso.</p>\n\n"
        '<div class="sspss-stats">\n'
        f'<span class="sspss-stat"><b>{len(subjects)}</b> materie</span>\n'
        f'<span class="sspss-stat"><b>{n_pages_now}</b> fascicoli di appunti</span>\n'
        '<span class="sspss-stat"><b>PDF</b> per ogni appunto</span>\n'
        '<span class="sspss-stat sspss-stat--visits" hidden><b></b> visite al sito</span>\n'
        "</div>\n\n"
        "</div>\n\n"
        '<div class="sspss-switch" data-active="az" role="group" aria-label="Ordinamento materie">\n'
        '<span class="sspss-switch__thumb"></span>\n'
        '<button type="button" data-sort="az" aria-pressed="true">A–Z</button>\n'
        '<button type="button" data-sort="views" aria-pressed="false">Più visitate</button>\n'
        "</div>\n\n"
        f'<div class="grid cards" markdown>\n\n{cards_md}\n\n</div>\n\n'
        '<div class="sspss-dlbanner" markdown>\n\n'
        ':material-folder-download:{ .lg .middle } **Ti serve tutto insieme?** '
        "Nel centro download spunti appunti e materiali e li scarichi in un unico zip. "
        "[Apri il centro download →](download/)\n\n"
        "</div>\n",
        encoding="utf-8")



    # Centro download: pagina con checkbox per materia, zip costruito dal browser
    subj_order = [d.name for d in subjects]
    by_subject: dict[str, list[dict]] = {}
    for item in DOWNLOADS:
        by_subject.setdefault(item["subject"], []).append(item)

    def dl_item(it):
        zip_path = "/".join(x for x in (it["subject"], it["sub"], it["folder"],
                                        f'{it["label"]}.{it["ext"]}') if x)
        return (f'<label class="sspss-dl__item"><input type="checkbox" class="sspss-dl-box" '
                f'data-url="../{it["url"]}" data-zip="{zip_path}">'
                f'<span>{it["label"]}</span><em>.{it["ext"]}</em></label>')

    def dl_block(items):
        lines = []
        items = sorted(items, key=lambda x: ((x["folder"] or ""), natkey(Path(x["label"]))))
        last = object()
        for it in items:
            if it["folder"] != last:
                if it["folder"]:
                    lines += [f'<p class="sspss-materials__group">{it["folder"]}</p>', ""]
                last = it["folder"]
            lines.append(dl_item(it))
        return lines

    dl_lines = ["---", "title: Centro download", "---", "",
                '<nav class="sspss-crumb"><a href="../">Home</a>'
                '<span class="sspss-crumb__sep">/</span><span>Centro download</span></nav>', "",
                "# Centro download", "",
                '<p class="sspss-dl__lead">Spunta quello che ti serve — appunti in PDF e materiali '
                "del corso, materia per materia — e scaricalo in un unico file zip.</p>", ""]
    for subj in subj_order:
        items = by_subject.get(subj)
        if not items:
            continue
        dl_lines += [f"## {subj}", "",
                     f'<div class="sspss-dl" data-subject="{subj}" markdown>',
                     '<label class="sspss-dl__all"><input type="checkbox" class="sspss-dl-all">'
                     " Seleziona tutto</label>", ""]
        dl_lines += dl_block([it for it in items if not it["sub"]])
        subs = sorted({it["sub"] for it in items if it["sub"]})
        for sub in subs:
            dl_lines += ["", f"### {sub}", ""]
            dl_lines += dl_block([it for it in items if it["sub"] == sub])
        dl_lines += ["", "</div>", ""]
    dl_lines += ['<div class="sspss-dlbar">',
                 '<span class="sspss-dlbar__count">Nessun file selezionato</span>',
                 '<button type="button" class="md-button sspss-dlbar__go" disabled>'
                 "Scarica lo zip</button>", "</div>", ""]
    (DOCS / "download.md").write_text("\n".join(dl_lines), encoding="utf-8")

    # Template override: pannello "Materie" a tutta larghezza nell'header
    ovr = ROOT / "overrides"
    ovr.mkdir(exist_ok=True)
    mega_items = []
    for d in subjects:
        icon, desc = SUBJECTS.get(d.name, (DEFAULT_ICON, "Appunti e materiali"))
        icon_path = icon.replace("material-", "material/") + ".svg"
        href = urllib.parse.quote(d.name) + "/"
        mega_items.append(
            f'<a class="sspss-mega__item" href="{{{{ base_url }}}}/{href}">'
            f'<span class="sspss-mega__icon">{{% include ".icons/{icon_path}" %}}</span>'
            f'<span class="sspss-mega__text"><b>{d.name}</b><small>{desc}</small></span></a>'
        )
    (ovr / "main.html").write_text(
        "{% extends \"base.html\" %}\n"
        "{% block header %}\n{{ super() }}\n"
        '<div class="sspss-mega" id="sspss-mega" hidden>\n'
        '<div class="sspss-mega__grid">\n' + "\n".join(mega_items) + "\n</div>\n"
        '<div class="sspss-mega__foot">'
        '<a class="sspss-mega__dl" href="{{ base_url }}/download/">'
        '<span class="sspss-mega__icon">{% include ".icons/material/folder-download.svg" %}</span>'
        '<span class="sspss-mega__text"><b>Centro download</b>'
        "<small>Appunti e materiali in un unico zip</small></span></a>"
        "</div>\n</div>\n"
        "{% endblock %}\n", encoding="utf-8")

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

/* ------ Shell: niente menu a sinistra, indice della pagina al suo posto ------ */
.md-grid { max-width: 72rem; }
.md-main__inner { margin-top: 1.1rem; }
.md-sidebar--primary, .md-header label[for="__drawer"] { display: none !important; }
.md-sidebar--secondary { order: 0; }
.md-sidebar__scrollwrap { margin: 0 .3rem; }

/* Indice: rail dinamico che segue la lettura */
.md-nav--secondary > .md-nav__title {
  font-size: .58rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase;
  color: var(--md-default-fg-color--light);
  padding-left: .6rem;
}
.md-nav--secondary .md-nav__list { border-left: 2px solid var(--sspss-hairline); }
.md-nav--secondary .md-nav__item { padding: 0; }
.md-nav--secondary .md-nav__link {
  position: relative;
  margin: 0; padding: .18rem .6rem;
  border-radius: 0 8px 8px 0;
  color: var(--md-default-fg-color--light);
}
.md-nav--secondary .md-nav__link:hover { background: var(--md-accent-fg-color--transparent); color: var(--md-typeset-a-color); }
.md-nav--secondary .md-nav__link--active { color: var(--md-typeset-a-color); font-weight: 600; background: var(--md-accent-fg-color--transparent); }
.md-nav--secondary .md-nav__link--active::before {
  content: ""; position: absolute; left: -2px; top: 12%;
  height: 76%; width: 2px; border-radius: 2px;
  background: var(--sspss-red);
}
[data-md-color-scheme="slate"] .md-nav--secondary .md-nav__link--active::before { background: #FF8A75; }
/* Le sottovoci compaiono solo nella sezione in cui ti trovi */
.md-nav--secondary .md-nav__item .md-nav { display: none; }
.md-nav--secondary .md-nav__item:has(.md-nav__link--active) > .md-nav { display: block; }

/* Colonna destra: card Materiali */
.sspss-right { order: 2; width: 12.1rem; flex-shrink: 0; padding: 1.2rem .3rem 0; align-self: flex-start; position: sticky; top: 4.6rem; }
.sspss-card {
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 16px;
  box-shadow: var(--sspss-shadow-sm);
  padding: .65rem .75rem;
}
.sspss-card__head { display: flex; align-items: center; cursor: pointer; user-select: none; margin: 0 !important; }
.sspss-arrow {
  margin-left: auto; display: inline-flex; padding: .1rem;
  background: none; border: none; cursor: pointer; border-radius: 6px;
  color: var(--md-default-fg-color--light);
}
.sspss-card__head:hover .sspss-arrow { background: var(--md-accent-fg-color--transparent); color: var(--md-typeset-a-color); }
.sspss-arrow svg { fill: currentColor; transition: transform .2s; }
body.sspss-hide-mat .sspss-arrow svg { transform: rotate(-90deg); }
body.sspss-hide-mat .sspss-card .sspss-materials > ul { display: none; }
.sspss-materials__title {
  font-size: .58rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase;
  color: var(--md-default-fg-color--light);
}
.sspss-materials__group {
  font-size: .56rem; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
  color: var(--sspss-red);
  margin: .6rem 0 0 !important;
}
[data-md-color-scheme="slate"] .sspss-materials__group { color: #FF8A75; }
body.sspss-hide-mat .sspss-card .sspss-materials .sspss-materials__group { display: none; }
.sspss-card .sspss-materials > ul { list-style: none; margin: .4rem 0 0; padding: 0; font-size: .62rem; }
.sspss-card .sspss-materials > ul li { margin: .15rem 0; display: flex; align-items: center; gap: .3rem; }
.sspss-materials .twemoji { color: var(--sspss-red); flex: none; display: inline-flex; }
[data-md-color-scheme="slate"] .sspss-materials .twemoji { color: #FF8A75; }
.sspss-materials .twemoji svg { width: .85rem; height: .85rem; max-height: none; fill: currentColor; }
.sspss-card .sspss-materials a { color: var(--md-default-fg-color); }
.sspss-card .sspss-materials a:hover { color: var(--md-typeset-a-color); }
/* In pagina resta solo su schermi stretti, come blocco in fondo */
@media screen and (min-width: 60em) { .md-content .sspss-materials { display: none; } }
@media screen and (max-width: 59.984375em) {
  .md-content .sspss-materials {
    margin-top: 1.4rem; padding: .8rem 1rem;
    background: var(--md-default-bg-color);
    border: 1px solid var(--sspss-hairline); border-radius: 12px;
  }
}

/* Mega menu Materie */
.sspss-menu-btn {
  display: inline-flex; align-items: center; gap: .15rem;
  margin-left: .4rem; padding: .35rem .8rem;
  border: none; border-radius: 999px;
  background: none; color: inherit;
  font: inherit; font-weight: 600; font-size: .7rem;
  cursor: pointer;
  transition: background .15s, color .15s;
}
.sspss-menu-btn svg { fill: currentColor; transition: transform .2s; }
.sspss-menu-btn:hover, .sspss-menu-btn.open { background: var(--md-accent-fg-color--transparent); color: var(--md-typeset-a-color); }
.sspss-menu-btn.open svg { transform: rotate(180deg); }
.sspss-mega {
  position: fixed; z-index: 3;
  left: 50%; transform: translateX(-50%) translateY(-8px);
  width: min(72rem, calc(100% - 1.6rem));
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 20px;
  box-shadow: var(--sspss-shadow-lg);
  padding: .8rem;
  opacity: 0; pointer-events: none; visibility: hidden;
  transition: opacity .18s, transform .18s, visibility .18s;
  max-height: calc(100vh - 6rem); overflow: auto;
}
.sspss-mega.open { opacity: 1; transform: translateX(-50%) translateY(0); pointer-events: auto; visibility: visible; }
.sspss-mega__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: .3rem; }
.sspss-mega__item {
  display: flex; align-items: center; gap: .55rem;
  padding: .5rem .6rem; border-radius: 12px;
  color: var(--md-default-fg-color);
  transition: background .15s, transform .15s;
}
.sspss-mega__item:hover { background: var(--md-accent-fg-color--transparent); transform: translateY(-1px); }
.sspss-mega__icon {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: 1.9rem; height: 1.9rem; border-radius: 10px;
  background: var(--md-accent-fg-color--transparent);
  color: var(--sspss-red);
}
[data-md-color-scheme="slate"] .sspss-mega__icon { color: #FF8A75; }
.sspss-mega__icon svg { width: 1.1rem; height: 1.1rem; fill: currentColor; }
.sspss-mega__text { display: flex; flex-direction: column; line-height: 1.25; min-width: 0; }
.sspss-mega__text b { font-family: "Space Grotesk", sans-serif; font-size: .68rem; font-weight: 600; }
.sspss-mega__text small { font-size: .58rem; color: var(--md-default-fg-color--light); }
.sspss-mega__item--here { background: var(--md-accent-fg-color--transparent); }
.sspss-mega__item--here b { color: var(--md-typeset-a-color); }

/* Centro download */
.sspss-dl__lead { color: var(--md-default-fg-color--light); }
.sspss-dl { position: relative; margin: .4rem 0 1.4rem; }
.sspss-dl__all {
  display: inline-flex; align-items: center; gap: .45rem;
  font-size: .62rem; font-weight: 600; cursor: pointer;
  color: var(--md-default-fg-color--light);
}
/* La spunta sta sulla riga del titolo della materia */
@media screen and (min-width: 45em) {
  .sspss-dl__all { position: absolute; right: 0; top: -2.15rem; }
}
.sspss-dl__all:hover { color: var(--md-typeset-a-color); }
/* Sotto-materie (h3 dentro la sezione): divisione ben visibile */
.sspss-dl h3 {
  margin: 1.1em 0 .25em !important;
  padding-top: .7em;
  border-top: 1px solid var(--sspss-hairline);
}
.sspss-dl .sspss-materials__group { margin: .55rem 0 .1rem !important; }
.sspss-dl__item {
  display: flex; align-items: center; gap: .55rem;
  padding: .32rem .5rem; margin: 0 -.5rem;
  border-radius: 8px; cursor: pointer;
  font-size: .68rem;
}
.sspss-dl__item:hover { background: var(--md-accent-fg-color--transparent); }
.sspss-dl__item em {
  margin-left: auto; font-style: normal;
  font-size: .55rem; font-weight: 700; letter-spacing: .04em;
  color: var(--sspss-red);
  background: var(--md-accent-fg-color--transparent);
  border-radius: 999px; padding: .1em .6em;
}
[data-md-color-scheme="slate"] .sspss-dl__item em { color: #FF8A75; }
.sspss-dl input[type="checkbox"], .sspss-dlbanner input { accent-color: var(--sspss-red); }
.sspss-dl input[type="checkbox"] { width: .85rem; height: .85rem; flex: none; }
.sspss-dlbar {
  position: sticky; bottom: .8rem; z-index: 2;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  margin-top: 1.4rem; padding: .55rem .6rem .55rem 1rem;
  background: var(--sspss-surface);
  border: 1px solid var(--sspss-hairline);
  border-radius: 999px;
  box-shadow: var(--sspss-shadow-lg);
}
.sspss-dlbar__count { font-size: .66rem; color: var(--md-default-fg-color--light); }
.sspss-dlbar__go:disabled { opacity: .45; cursor: not-allowed; transform: none !important; }

/* Pulsante Centro download in alto a destra nella home */
.md-content__inner { position: relative; }
.md-typeset .sspss-dlbtn { display: inline-flex; align-items: center; gap: .35em; }
.md-typeset .sspss-dlbtn .twemoji svg { width: 1em; height: 1em; max-height: none; fill: currentColor; }
@media screen and (min-width: 60em) {
  .md-content__inner:has(.sspss-hero) .sspss-dlbtn { position: absolute; top: 1.2rem; right: 0; margin: 0; }
}
@media screen and (max-width: 59.984375em) {
  .md-content__inner:has(.sspss-hero) .sspss-dlbtn { display: table; margin: .6rem auto 0; }
}

/* Banner verso il centro download (home) */
.sspss-dlbanner {
  display: flex; align-items: center; gap: .8rem;
  margin-top: 1.2rem; padding: .9rem 1.2rem;
  background: var(--sspss-surface);
  border: 1px dashed var(--sspss-th-border);
  border-radius: 16px;
  font-size: .72rem;
}
.sspss-dlbanner p { margin: 0 !important; }
.sspss-dlbanner .twemoji.lg {
  display: inline-flex; align-items: center; justify-content: center;
  width: 2.1rem; height: 2.1rem; flex: none;
  border-radius: 11px;
  background: var(--md-accent-fg-color--transparent);
  color: var(--sspss-red);
}
[data-md-color-scheme="slate"] .sspss-dlbanner .twemoji.lg { color: #FF8A75; }
.sspss-dlbanner .twemoji.lg svg { width: 1.2rem; height: 1.2rem; max-height: none; }

/* Voce centro download nel mega menu */
.sspss-mega__dl {
  display: flex; align-items: center; gap: .55rem;
  margin-top: .5rem; padding: .55rem .6rem;
  border-top: 1px solid var(--sspss-hairline);
  border-radius: 0 0 12px 12px;
  color: var(--md-default-fg-color);
}
.sspss-mega__dl:hover { background: var(--md-accent-fg-color--transparent); }
.sspss-mega__dl b { font-family: "Space Grotesk", sans-serif; font-size: .68rem; font-weight: 600; }
.sspss-mega__dl small { display: block; font-size: .58rem; color: var(--md-default-fg-color--light); }

/* Piede del mega menu: centro download e glossario */
.sspss-mega__foot { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .5rem; padding-top: .4rem; border-top: 1px solid var(--sspss-hairline); }
.sspss-mega__foot .sspss-mega__dl { flex: 1 1 14rem; margin-top: 0; border-top: none; border-radius: 12px; }

/* Data di aggiornamento in fondo alla pagina */
.sspss-updated {
  margin-top: 2rem !important; padding-top: .7rem;
  border-top: 1px solid var(--sspss-hairline);
  font-size: .62rem; color: var(--md-default-fg-color--light);
}

/* Copertina: solo nel PDF */
.sspss-cover { display: none; }

/* Pulsante quiz */
.md-typeset .sspss-quizlink { margin-left: .4rem; display: inline-flex; align-items: center; gap: .35em; }
.md-typeset .sspss-quizlink .twemoji svg, .sspss-quizlink--rail .twemoji svg { width: 1em; height: 1em; max-height: none; fill: currentColor; }
.sspss-quizlink--rail {
  display: flex; align-items: center; justify-content: center; gap: .4em;
  margin: 0 0 .6rem;
  padding: .6em 1em;
  border-radius: 14px;
  background: var(--sspss-red); color: #fff;
  font-size: .68rem; font-weight: 600;
  box-shadow: 0 6px 14px rgba(179, 38, 30, .25);
  transition: transform .15s, background .15s;
}
.sspss-quizlink--rail:hover { background: var(--sspss-red-dark); color: #fff; transform: translateY(-1px); }
.sspss-quizlink--rail .twemoji { display: inline-flex; }

/* Pulsante glossario */
.md-typeset .sspss-glosslink { margin-left: .4rem; display: inline-flex; align-items: center; gap: .35em; }
.md-typeset .sspss-glosslink .twemoji svg, .sspss-glosslink--rail .twemoji svg { width: 1em; height: 1em; max-height: none; fill: currentColor; }
.sspss-glosslink--rail {
  display: flex; align-items: center; justify-content: center; gap: .4em;
  margin: 0 0 .6rem; padding: .55em 1em;
  border-radius: 14px;
  background: var(--sspss-surface); color: var(--md-typeset-a-color);
  border: 1px solid var(--sspss-th-border);
  font-size: .68rem; font-weight: 600;
  transition: transform .15s, background .15s;
}
.sspss-glosslink--rail:hover { background: var(--md-accent-fg-color--transparent); transform: translateY(-1px); }
.sspss-glosslink--rail .twemoji { display: inline-flex; }

/* Quiz */
.sspss-quiz__stop {
  font: inherit; font-size: .6rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
  padding: .15em .8em; cursor: pointer;
  background: none; color: var(--md-default-fg-color--light);
  border: 1px solid var(--sspss-hairline); border-radius: 999px;
}
.sspss-quiz__stop:hover { color: var(--md-typeset-a-color); border-color: var(--sspss-th-border); }
.sspss-quiz__head { align-items: center; }
.sspss-quiz__partial { font-size: .66rem; color: var(--md-default-fg-color--light); }
.sspss-quiz__label { font-size: .58rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; color: var(--md-default-fg-color--light); margin: 1.1rem 0 .3rem !important; }
.md-typeset ul.sspss-quiz__review { list-style: none; margin: 0; padding: 0; }
.md-typeset ul.sspss-quiz__review li {
  display: flex; align-items: baseline; justify-content: space-between; gap: 1rem;
  margin: 0; padding: .45rem .1rem;
  border-bottom: 1px solid var(--sspss-hairline);
  font-size: .72rem;
}
.sspss-quiz__review a { font-weight: 600; }
.sspss-quiz__review span { flex: none; font-size: .62rem; color: var(--md-default-fg-color--light); }
.sspss-quiz { max-width: 34rem; margin: 1rem 0; }
.sspss-quiz__head { display: flex; justify-content: space-between; font-size: .62rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--md-default-fg-color--light); }
.sspss-quiz__bar { height: 4px; margin: .4rem 0 1rem; border-radius: 4px; background: var(--sspss-hairline); overflow: hidden; }
.sspss-quiz__bar span { display: block; height: 100%; background: var(--sspss-red); transition: width .3s; }
.sspss-quiz__q { font-family: "Space Grotesk", sans-serif; font-size: 1rem; font-weight: 600; line-height: 1.35 !important; color: var(--sspss-ink); margin-bottom: .9rem !important; }
.sspss-quiz__opts { display: grid; gap: .45rem; }
.sspss-quiz__opt {
  font: inherit; font-size: .72rem; text-align: left; line-height: 1.4;
  padding: .65rem .9rem; cursor: pointer;
  background: var(--sspss-surface); color: var(--md-default-fg-color);
  border: 1px solid var(--sspss-hairline); border-radius: 12px;
  transition: border-color .15s, background .15s, transform .15s;
}
.sspss-quiz__opt:hover:not(:disabled) { border-color: var(--sspss-th-border); background: var(--md-accent-fg-color--transparent); transform: translateY(-1px); }
.sspss-quiz__opt:disabled { cursor: default; opacity: .6; }
.sspss-quiz__opt.is-right { opacity: 1; border-color: #2E7D32; background: rgba(46, 125, 50, .12); font-weight: 600; }
.sspss-quiz__opt.is-wrong { opacity: 1; border-color: var(--sspss-red); background: rgba(179, 38, 30, .1); }
.sspss-quiz__after { margin-top: .9rem; }
.sspss-quiz__verdict { font-weight: 700; margin: 0 !important; }
.sspss-quiz__verdict.is-right { color: #2E7D32; }
.sspss-quiz__verdict.is-wrong { color: var(--sspss-red); }
[data-md-color-scheme="slate"] .sspss-quiz__verdict.is-right { color: #81C784; }
[data-md-color-scheme="slate"] .sspss-quiz__verdict.is-wrong { color: #FF8A75; }
.sspss-quiz__why { font-size: .7rem; color: var(--md-default-fg-color--light); margin: .2rem 0 .8rem !important; }
.sspss-quiz__final { font-family: "Space Grotesk", sans-serif; font-size: 3rem; font-weight: 700; line-height: 1 !important; color: var(--sspss-red); margin: 1rem 0 .3rem !important; }
[data-md-color-scheme="slate"] .sspss-quiz__final { color: #FF8A75; }
.sspss-quiz__row { display: flex; align-items: center; gap: 1rem; margin-top: 1rem; }
.sspss-quiz__back { font-size: .7rem; font-weight: 600; }

/* Ingrandimento immagini */
.md-content img.sspss-zoomable { cursor: zoom-in; }
.sspss-lightbox {
  position: fixed; inset: 0; z-index: 20;
  display: flex; align-items: center; justify-content: center;
  padding: 1.2rem;
  background: rgba(20, 16, 15, .88);
  cursor: zoom-out;
}
.sspss-lightbox img { max-width: 100%; max-height: 100%; border-radius: 10px; background: #fff; box-shadow: 0 20px 60px rgba(0,0,0,.5); }

/* Barra di progresso lettura */
#sspss-progress {
  position: fixed; top: 0; left: 0; height: 3px; width: 0;
  background: var(--sspss-red); border-radius: 0 2px 2px 0; z-index: 10;
}
[data-md-color-scheme="slate"] #sspss-progress { background: #FF8A75; }

/* Briciole di pane */
.sspss-crumb {
  display: flex; flex-wrap: wrap; gap: .5ch;
  font-size: .62rem; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase;
  color: var(--md-default-fg-color--light);
  margin-bottom: .8rem;
}
.sspss-crumb a { color: inherit; }
.sspss-crumb a:hover { color: var(--md-typeset-a-color); }
.sspss-crumb > span:last-child { color: var(--sspss-red); }
[data-md-color-scheme="slate"] .sspss-crumb > span:last-child { color: #FF8A75; }
.sspss-crumb__sep { opacity: .5; }
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
.md-typeset .grid.cards > ul > li > p:last-child { display: flex; align-items: center; justify-content: space-between; }
.md-typeset .grid.cards > ul > li > p:last-child a { font-weight: 600; }
/* Tutta la card è cliccabile */
.md-typeset .grid.cards > ul > li > p:last-child a::after { content: ""; position: absolute; inset: 0; }
.sspss-badge-new {
  margin-left: auto; flex: none;
  font-size: .52rem; font-weight: 700;
  letter-spacing: .08em; text-transform: uppercase;
  color: var(--sspss-red);
  background: var(--md-accent-fg-color--transparent);
  border: 1px solid var(--sspss-th-border);
  border-radius: 999px; padding: .2em .7em;
}
[data-md-color-scheme="slate"] .sspss-badge-new { color: #FF8A75; }
.sspss-views { font-size: .6rem; color: var(--md-default-fg-color--light); }
/* Interruttore di ordinamento: segmented control con cursore che scivola */
.sspss-switch {
  position: relative;
  display: grid; grid-template-columns: 1fr 1fr;
  width: 15rem; max-width: 100%;
  margin: 0 auto 1.1rem;
  padding: 3px;
  border-radius: 999px;
  background: rgba(28, 25, 23, .07);
  border: 1px solid var(--sspss-hairline);
  cursor: pointer; user-select: none;
}
[data-md-color-scheme="slate"] .sspss-switch { background: rgba(237, 231, 228, .08); }
.sspss-switch__thumb {
  position: absolute; top: 3px; bottom: 3px; left: 3px;
  width: calc(50% - 3px);
  border-radius: 999px;
  background: var(--sspss-surface);
  box-shadow: 0 2px 8px rgba(28, 25, 23, .18);
  transition: transform .35s cubic-bezier(.3, 1.45, .45, 1);
}
[data-md-color-scheme="slate"] .sspss-switch__thumb { background: #3A302D; box-shadow: 0 2px 8px rgba(0,0,0,.5); }
.sspss-switch[data-active="views"] .sspss-switch__thumb { transform: translateX(100%); }
.sspss-switch button {
  position: relative; z-index: 1;
  font: inherit; font-size: .62rem; font-weight: 600;
  padding: .42em 0;
  background: none; border: none; cursor: pointer;
  color: var(--md-default-fg-color--light);
  transition: color .2s;
}
.sspss-switch button[aria-pressed="true"] { color: var(--sspss-red); }
[data-md-color-scheme="slate"] .sspss-switch button[aria-pressed="true"] { color: #FF8A75; }

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

@media print {
  .md-typeset .md-button, .sspss-materials, .sspss-crumb, #sspss-progress, .sspss-right, .sspss-lightbox { display: none !important; }
  .sspss-cover {
    display: flex; flex-direction: column; justify-content: center;
    height: 238mm; box-sizing: border-box; overflow: hidden; break-inside: avoid;
    margin: 0 !important;
    padding: 0 8mm;
    border-left: 6mm solid #B3261E;
    break-after: page; page-break-after: always;
  }
  .sspss-cover p { margin: 0 !important; }
  /* il titolo centrato degli appunti è già in copertina */
  .md-typeset h1[align="center"],
  .md-typeset h1[align="center"] + p[align="center"],
  .md-typeset h1[align="center"] + p[align="center"] + hr { display: none !important; }
  /* Indice del PDF (inserito da make_pdfs.py) */
  .sspss-printtoc { break-after: page; page-break-after: always; padding-top: 4mm; }
  .sspss-printtoc__title {
    font-family: "Space Grotesk", sans-serif; font-size: 22pt; font-weight: 700;
    letter-spacing: -.01em; color: #1C1917; margin: 0 0 8mm !important;
    padding-bottom: 3mm; border-bottom: 2px solid #B3261E;
  }
  .sspss-printtoc ol { list-style: none; margin: 0 !important; padding: 0 !important; }
  .sspss-printtoc li { margin: 0 !important; padding: 0 !important; break-inside: avoid; }
  .sspss-printtoc__row { display: flex; align-items: baseline; gap: 2mm; font-size: 10.5pt; line-height: 1.45; color: #1C1917; }
  .sspss-printtoc__row--1 { font-weight: 700; margin-top: 3.5mm; }
  .sspss-printtoc__row--2 { padding-left: 6mm; color: #44403C; }
  .sspss-printtoc__dots { flex: 1; border-bottom: 1px dotted #A8A29E; transform: translateY(-1mm); }
  .sspss-printtoc__num { font-variant-numeric: tabular-nums; min-width: 7mm; text-align: right; }
  .sspss-printtoc__end { position: absolute; color: #fff; font-size: 1pt; }
  .sspss-cover__kicker { font-size: 11pt; font-weight: 600; letter-spacing: .14em; text-transform: uppercase; color: #B3261E; }
  .sspss-cover .sspss-cover__title { font-family: "Space Grotesk", sans-serif; font-size: 40pt; font-weight: 700; line-height: 1.1 !important; letter-spacing: -.02em; color: #1C1917; margin: 8mm 0 4mm !important; }
  .sspss-cover__sub { font-size: 15pt; color: #57534E; }
  .sspss-cover .sspss-cover__meta { font-size: 10pt; color: #78716C; margin-top: 30mm !important; }
  .md-content__inner { background: #fff; border: none; box-shadow: none; padding: 0; margin: 0 !important; }
  .md-content__inner::before { display: none !important; }
  .md-main__inner { margin-top: 0 !important; }
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
        """// Interfaccia del sito: mega menu Materie, indice a sinistra, card Materiali,
// barra di progresso lettura e statistiche GoatCounter.
(function () {
  var GOATCOUNTER = "appunti-sspss";  // codice del sito su goatcounter.com
  var CHEVRON = '<svg viewBox="0 0 24 24" width="20" height="20"><path d="M7.41 8.58 12 13.17l4.59-4.59L18 10l-6 6-6-6 1.41-1.42Z"/></svg>';

  function get(key) { try { return localStorage.getItem("sspss-" + key) === "1"; } catch (e) { return false; } }
  function set(key, v) { try { localStorage.setItem("sspss-" + key, v ? "1" : "0"); } catch (e) {} }

  /* --- Logo + titolo riportano alla home --- */
  function initHome() {
    var logo = document.querySelector(".md-header__button.md-logo");
    var title = document.querySelector(".md-header__title");
    if (!logo || !title) return;
    title.style.cursor = "pointer";
    title.setAttribute("role", "link");
    title.addEventListener("click", function () { location.href = logo.href; });
  }

  /* --- Mega menu Materie --- */
  function initMega() {
    var header = document.querySelector(".md-header__inner");
    var panel = document.getElementById("sspss-mega");
    if (!header || !panel) return;
    panel.removeAttribute("hidden");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sspss-menu-btn";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "sspss-mega");
    btn.innerHTML = "Materie " + CHEVRON;
    header.insertBefore(btn, document.querySelector(".md-header__option") || null);

    // Evidenzia la materia della pagina corrente
    var here = decodeURIComponent(location.pathname);
    panel.querySelectorAll(".sspss-mega__item").forEach(function (a) {
      var p = decodeURIComponent(new URL(a.href).pathname);
      if (here.indexOf(p) === 0) a.classList.add("sspss-mega__item--here");
    });

    function open(v) {
      if (v) {
        var r = document.querySelector(".md-header").getBoundingClientRect();
        panel.style.top = (r.bottom + 8) + "px";
      }
      panel.classList.toggle("open", v);
      btn.classList.toggle("open", v);
      btn.setAttribute("aria-expanded", v ? "true" : "false");
    }
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      open(!panel.classList.contains("open"));
    });
    document.addEventListener("click", function (e) {
      if (panel.classList.contains("open") && !panel.contains(e.target)) open(false);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") open(false);
    });
  }

  /* --- Indice a sinistra: etichetta --- */
  function initToc() {
    var title = document.querySelector(".md-sidebar--secondary .md-nav--secondary > .md-nav__title");
    if (title) title.textContent = "In questa pagina";
  }

  /* --- Materiali: dal fondo pagina a card richiudibile a destra --- */
  /* --- Colonna destra (creata solo quando serve) --- */
  function getRail() {
    var rail = document.querySelector(".sspss-right");
    if (rail) return rail;
    var inner = document.querySelector(".md-main__inner");
    if (!inner) return null;
    rail = document.createElement("aside");
    rail.className = "sspss-right";
    inner.appendChild(rail);
    return rail;
  }
  function wide() { return window.matchMedia("(min-width: 60em)").matches; }

  /* --- Pulsante "Fai il quiz": su desktop sale nella colonna destra --- */
  function initQuizLink() {
    var link = document.querySelector(".md-content a.sspss-quizlink");
    if (!link || !wide()) return;  // su mobile resta accanto al pulsante PDF
    var rail = getRail();
    if (!rail) return;
    link.classList.add("sspss-quizlink--rail");
    rail.appendChild(link);
  }
  function initGlossLink() {
    var link = document.querySelector(".md-content a.sspss-glosslink");
    if (!link || !wide()) return;
    var rail = getRail();
    if (!rail) return;
    link.classList.add("sspss-glosslink--rail");
    rail.appendChild(link);
  }

  function initMaterials() {
    var src = document.querySelector(".md-content .sspss-materials");
    if (!src) return;
    if (!wide()) return;  // su mobile resta in pagina
    var rail = getRail();
    if (!rail) return;
    var card = document.createElement("div");
    card.className = "sspss-card";
    var head = src.querySelector(".sspss-materials__title");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sspss-arrow";
    btn.innerHTML = CHEVRON;
    head.appendChild(btn);
    head.classList.add("sspss-card__head");
    card.appendChild(src);
    rail.appendChild(card);

    function apply(hidden) {
      document.body.classList.toggle("sspss-hide-mat", hidden);
      btn.setAttribute("aria-expanded", hidden ? "false" : "true");
      btn.title = (hidden ? "Mostra" : "Nascondi") + " materiali";
      btn.setAttribute("aria-label", btn.title);
    }
    head.addEventListener("click", function () {
      var hidden = !document.body.classList.contains("sspss-hide-mat");
      set("hide-mat", hidden); apply(hidden);
    });
    apply(get("hide-mat"));
  }

  /* --- Barra di progresso lettura --- */
  function initProgress() {
    if (!document.querySelector(".md-content")) return;
    if (document.querySelector(".sspss-hero")) return;  // niente barra in home
    var bar = document.createElement("div");
    bar.id = "sspss-progress";
    document.body.appendChild(bar);
    var ticking = false;
    function update() {
      var h = document.documentElement;
      var max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + "%";
      ticking = false;
    }
    addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(update); }
    }, { passive: true });
    update();
  }

  /* --- GoatCounter: conteggio visite + visite per materia + ordinamento --- */
  function gcBase() { return "https://" + GOATCOUNTER + ".goatcounter.com"; }

  function initCount() {
    if (!GOATCOUNTER || location.hostname === "localhost" || location.hostname === "127.0.0.1") return;
    var sc = document.createElement("script");
    sc.async = true;
    sc.dataset.goatcounter = gcBase() + "/count";
    sc.src = "https://gc.zgo.at/count.js";
    document.head.appendChild(sc);
  }

  /* Conteggi: TOTAL decide se GoatCounter è attivo; i percorsi 404 valgono 0 */
  function gcFetch(path) {
    return fetch(gcBase() + "/counter/" + encodeURIComponent(path) + ".json")
      .then(function (r) {
        if (r.status === 404) return { miss: true };
        if (!r.ok) return null;
        return r.json();
      })
      .catch(function () { return null; });
  }
  function gcCount(path) {
    // GoatCounter normalizza senza slash finale; prova le varianti in ordine
    var tries = [path.replace(/\\/$/, ""), path, decodeURIComponent(path).replace(/\\/$/, ""), decodeURIComponent(path)]
      .filter(function (v, i, a) { return a.indexOf(v) === i; });
    var sawMiss = false;
    function next(i) {
      if (i >= tries.length) return Promise.resolve(sawMiss ? 0 : null);
      return gcFetch(tries[i]).then(function (d) {
        if (d && !d.miss) return parseInt(String(d.count).replace(/\\D/g, ""), 10) || 0;
        if (d && d.miss) sawMiss = true;
        return next(i + 1);
      });
    }
    return next(0);
  }

  function siteRoot() {
    var logo = document.querySelector(".md-header__button.md-logo");
    return logo ? logo.href : location.href;
  }

  function initStats() {
    if (!GOATCOUNTER) return;
    initSwitch();
    // Prima il file statico aggiornato dalla CI (stesso dominio: passa anche con gli ad-blocker)
    fetch(new URL("assets/stats.json", siteRoot()))
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (st) {
        if (st && st.total != null) {
          renderTotal(st.total);
          initCardViews(function (path) {
            var key = decodeURIComponent(path);
            return Promise.resolve(st.paths && key in st.paths ? st.paths[key] : null);
          });
        } else {
          // Fallback: chiamate live a GoatCounter
          gcFetch("TOTAL").then(function (d) {
            if (!d || d.miss) return;
            renderTotal(parseInt(String(d.count).replace(/\\D/g, ""), 10) || 0);
            initCardViews(gcCount);
          });
        }
      });
  }

  function renderTotal(n) {
    var chip = document.querySelector(".sspss-stat--visits");
    if (!chip) return;
    chip.querySelector("b").textContent = n.toLocaleString("it-CH");
    chip.hidden = false;
  }

  function initCardViews(counter) {
    var grid = document.querySelector(".grid.cards > ul");
    if (!grid) return;
    [].slice.call(grid.children).forEach(function (li) {
      var a = li.querySelector("p:last-child a");
      var span = li.querySelector(".sspss-views");
      if (!a || !span) return;
      counter(new URL(a.href).pathname).then(function (n) {
        if (n == null) return;
        li.dataset.views = n;
        span.textContent = n.toLocaleString("it-CH") + (n === 1 ? " visita" : " visite");
        span.hidden = false;
      });
    });
  }

  function initSwitch() {
    var sw = document.querySelector(".sspss-switch");
    var grid = document.querySelector(".grid.cards > ul");
    if (!sw || !grid) return;
    var lis = [].slice.call(grid.children);
    lis.forEach(function (li, i) { li.dataset.az = i; });
    sw.addEventListener("click", function () {
      var by = sw.dataset.active === "az" ? "views" : "az";
      sw.dataset.active = by;
      sw.querySelectorAll("button").forEach(function (b) {
        b.setAttribute("aria-pressed", b.dataset.sort === by ? "true" : "false");
      });
      [].slice.call(grid.children)
        .sort(function (x, y) {
          return by === "views"
            ? (+(y.dataset.views || 0)) - (+(x.dataset.views || 0))
            : (+x.dataset.az) - (+y.dataset.az);
        })
        .forEach(function (li) { grid.appendChild(li); });
    });
  }

  /* --- Centro download: checkbox e zip --- */
  function initDownloads() {
    var boxes = [].slice.call(document.querySelectorAll(".sspss-dl-box"));
    var bar = document.querySelector(".sspss-dlbar");
    if (!boxes.length || !bar) return;
    var count = bar.querySelector(".sspss-dlbar__count");
    var go = bar.querySelector(".sspss-dlbar__go");

    function refresh() {
      var sel = boxes.filter(function (b) { return b.checked; });
      go.disabled = !sel.length;
      count.textContent = !sel.length ? "Nessun file selezionato"
        : sel.length === 1 ? "1 file selezionato" : sel.length + " file selezionati";
      document.querySelectorAll(".sspss-dl").forEach(function (sec) {
        var all = sec.querySelector(".sspss-dl-all");
        var own = [].slice.call(sec.querySelectorAll(".sspss-dl-box"));
        var n = own.filter(function (b) { return b.checked; }).length;
        all.checked = n === own.length;
        all.indeterminate = n > 0 && n < own.length;
      });
    }
    boxes.forEach(function (b) { b.addEventListener("change", refresh); });
    document.querySelectorAll(".sspss-dl").forEach(function (sec) {
      sec.querySelector(".sspss-dl-all").addEventListener("change", function () {
        var v = this.checked;
        sec.querySelectorAll(".sspss-dl-box").forEach(function (b) { b.checked = v; });
        refresh();
      });
    });
    refresh();

    function loadJSZip() {
      if (window.JSZip) return Promise.resolve();
      return new Promise(function (ok, no) {
        var sc = document.createElement("script");
        sc.src = new URL("assets/jszip.min.js", siteRoot());
        sc.onload = ok; sc.onerror = no;
        document.head.appendChild(sc);
      });
    }

    go.addEventListener("click", function () {
      var sel = boxes.filter(function (b) { return b.checked; });
      if (!sel.length) return;
      go.disabled = true;
      var done = 0, failed = [];
      loadJSZip().then(function () {
        var zip = new JSZip();
        return Promise.all(sel.map(function (b) {
          return fetch(b.dataset.url)
            .then(function (r) { if (!r.ok) throw 0; return r.blob(); })
            .then(function (blob) { zip.file(b.dataset.zip, blob); })
            .catch(function () { failed.push(b.dataset.zip.split("/").pop()); })
            .then(function () {
              done += 1;
              go.textContent = "Preparo lo zip… " + done + "/" + sel.length;
            });
        })).then(function () {
          go.textContent = "Comprimo…";
          return zip.generateAsync({ type: "blob" });
        }).then(function (blob) {
          var a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = "appunti-sspss.zip";
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 30000);
          go.textContent = "Scarica lo zip";
          go.disabled = false;
          count.textContent = failed.length
            ? "Zip pronto; " + failed.length + " file non trovati: " + failed.join(", ")
            : "Zip scaricato";
        });
      }).catch(function () {
        go.textContent = "Scarica lo zip";
        go.disabled = false;
        count.textContent = "Errore nel preparare lo zip, riprova";
      });
    });
  }

  /* --- Quiz --- */
  function shuffle(a) {
    a = a.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function initQuiz() {
    var box = document.querySelector(".sspss-quiz");
    if (!box) return;
    fetch(box.dataset.src)
      .then(function (r) { if (!r.ok) throw 0; return r.json(); })
      .then(function (all) { run(all); })
      .catch(function () { box.textContent = "Non riesco a caricare il quiz. Ricarica la pagina."; });

    function norm(t) { return String(t).toLowerCase().normalize("NFD").replace(/[^a-z0-9]/g, ""); }

    // Capitoli degli appunti: titolo -> ancora, letti dalla pagina della materia
    var back = box.dataset.back || "../";
    var anchors = fetch(back)
      .then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (html) {
        var map = {};
        var doc = new DOMParser().parseFromString(html, "text/html");
        doc.querySelectorAll(".md-content h1[id], .md-content h2[id], .md-content h3[id], .md-content h4[id], .md-content h5[id]")
          .forEach(function (h) {
            var c = h.cloneNode(true);
            c.querySelectorAll(".headerlink").forEach(function (x) { x.remove(); });
            var k = norm(c.textContent);
            if (!(k in map)) map[k] = h.id;
          });
        return map;
      })
      .catch(function () { return {}; });

    function run(all) {
      var qs = shuffle(all), i = 0, log = [];
      function score() { return log.filter(function (a) { return a.ok; }).length; }

      function question() {
        box.innerHTML = "";
        var q = qs[i];
        var head = el("div", "sspss-quiz__head");
        head.appendChild(el("span", "sspss-quiz__count", "Domanda " + (i + 1) + " di " + qs.length));
        var stop = el("button", "sspss-quiz__stop", "Termina ora");
        stop.type = "button";
        stop.addEventListener("click", result);
        head.appendChild(stop);
        box.appendChild(head);
        var bar = el("div", "sspss-quiz__bar");
        var fill = el("span");
        fill.style.width = (i / qs.length * 100) + "%";
        bar.appendChild(fill);
        box.appendChild(bar);
        box.appendChild(el("p", "sspss-quiz__q", q.q));

        var opts = el("div", "sspss-quiz__opts");
        var after = el("div", "sspss-quiz__after");
        shuffle([q.correct].concat(q.wrong)).forEach(function (text) {
          var b = el("button", "sspss-quiz__opt", text);
          b.type = "button";
          b.addEventListener("click", function () {
            var ok = text === q.correct;
            log.push({ cap: q.cap || "", ok: ok });
            [].forEach.call(opts.children, function (o) {
              o.disabled = true;
              if (o.textContent === q.correct) o.classList.add("is-right");
            });
            if (!ok) b.classList.add("is-wrong");
            after.appendChild(el("p", "sspss-quiz__verdict " + (ok ? "is-right" : "is-wrong"),
              ok ? "Giusto." : "Non proprio."));
            if (q.why) after.appendChild(el("p", "sspss-quiz__why", q.why));
            var next = el("button", "md-button sspss-quiz__next",
              i + 1 < qs.length ? "Avanti" : "Vedi il risultato");
            next.type = "button";
            next.addEventListener("click", function () { i += 1; i < qs.length ? question() : result(); });
            after.appendChild(next);
            next.focus();
          });
          opts.appendChild(b);
        });
        box.appendChild(opts);
        box.appendChild(after);
      }

      function result() {
        box.innerHTML = "";
        var done = log.length, right = score();
        var row = el("div", "sspss-quiz__row");
        var again = el("button", "md-button", done ? "Riprova" : "Ricomincia");
        again.type = "button";
        again.addEventListener("click", function () { run(all); });
        var home = el("a", "sspss-quiz__back", "Torna agli appunti");
        home.href = back;
        row.appendChild(again); row.appendChild(home);

        if (!done) {
          box.appendChild(el("p", "sspss-quiz__msg", "Non hai risposto a nessuna domanda, quindi non c'è niente da valutare."));
          box.appendChild(row);
          return;
        }
        var pct = Math.round(right / done * 100);
        box.appendChild(el("p", "sspss-quiz__final", right + " / " + done));
        if (done < qs.length) {
          box.appendChild(el("p", "sspss-quiz__partial",
            "Hai terminato prima: valutazione su " + done + " domande delle " + qs.length + " disponibili."));
        }

        // Analisi per capitolo
        var caps = {}, order = [];
        log.forEach(function (a) {
          if (!caps[a.cap]) { caps[a.cap] = { ok: 0, ko: 0 }; order.push(a.cap); }
          caps[a.cap][a.ok ? "ok" : "ko"] += 1;
        });
        var weak = order.filter(function (c) { return caps[c].ko > 0; })
          .sort(function (x, y) { return caps[y].ko - caps[x].ko; });
        var strong = order.filter(function (c) { return caps[c].ko === 0; });

        var msg;
        if (!weak.length) msg = "Tutte giuste: su questi argomenti sei solido.";
        else if (pct >= 80) msg = "Buon risultato. Gli errori sono concentrati in " +
          (weak.length === 1 ? "un solo capitolo" : weak.length + " capitoli") + ": basta un ripasso mirato.";
        else if (pct >= 50) msg = "Base discreta, ma " + (weak.length === 1 ? "un capitolo va rivisto" : weak.length + " capitoli vanno rivisti") + " prima di sentirti sicuro.";
        else msg = "C'è ancora da lavorare: conviene rileggere i capitoli qui sotto e poi riprovare.";
        if (weak.length && strong.length) {
          msg += " Vanno bene invece " + strong.length + (strong.length === 1 ? " capitolo" : " capitoli") + " su " + order.length + ".";
        }
        box.appendChild(el("p", "sspss-quiz__msg", msg));

        if (weak.length) {
          box.appendChild(el("p", "sspss-quiz__label", "Da ripassare"));
          var ul = el("ul", "sspss-quiz__review");
          weak.forEach(function (c) {
            var li = el("li");
            var a = el("a", null, c || "Appunti");
            a.href = back;
            li.appendChild(a);
            var n = caps[c].ko, tot = caps[c].ko + caps[c].ok;
            li.appendChild(el("span", null, n + (n === 1 ? " errore" : " errori") + " su " + tot));
            ul.appendChild(li);
            anchors.then(function (map) {
              var id = map[norm(c)];
              if (id) a.href = back + "#" + id;
            });
          });
          box.appendChild(ul);
        }
        box.appendChild(row);
      }

      question();
    }
  }

  /* --- Ingrandimento delle immagini al clic --- */
  function initZoom() {
    var imgs = document.querySelectorAll(".md-content img");
    if (!imgs.length) return;
    var layer = null;
    function close() { if (layer) { layer.remove(); layer = null; } }
    function open(img) {
      close();
      layer = el("div", "sspss-lightbox");
      var big = document.createElement("img");
      big.src = img.currentSrc || img.src;
      big.alt = img.alt || "";
      layer.appendChild(big);
      layer.addEventListener("click", close);
      document.body.appendChild(layer);
    }
    [].forEach.call(imgs, function (img) {
      if (img.closest("a")) return;
      img.classList.add("sspss-zoomable");
      img.addEventListener("click", function () { open(img); });
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  }

  function init() {
    initHome(); initMega(); initToc(); initQuizLink(); initGlossLink(); initMaterials(); initProgress();
    initCount(); initStats(); initDownloads(); initQuiz(); initZoom();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
""", encoding="utf-8")

    # Libreria zip servita dal sito stesso (niente CDN esterne)
    shutil.copy2(ROOT / "scripts" / "vendor" / "jszip.min.js", assets / "jszip.min.js")

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
