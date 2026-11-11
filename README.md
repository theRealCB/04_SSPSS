# Appunti SSPSS

Appunti dei **Moduli complementari SUP** (anno 2026/2027), organizzati in una cartella per materia.

## 📖 Il sito

Gli appunti si leggono comodamente qui:

**👉 https://therealcb.github.io/04_SSPSS/**

Il sito ha una pagina per materia, con ricerca, tema chiaro/scuro, il pulsante per scaricare il PDF e i materiali del corso (booklet, slide, documenti).

## Come funziona

Non serve fare niente: a ogni `git push` su `main` una GitHub Action ricostruisce il sito e lo pubblica da sola (ci mette circa un minuto).

- `build.py` legge le cartelle delle materie così come sono e genera le pagine
- `mkdocs.yml` è la configurazione del sito (tema [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/))
- `.github/workflows/deploy.yml` è il workflow che pubblica

## Struttura

```
Materia/
├── appunti.md      ← gli appunti (diventano la pagina del sito)
├── appunti.pdf     ← il PDF scaricabile (stesso nome del .md)
├── imm/            ← immagini usate negli appunti
└── altri file      ← pdf/docx/pptx: finiscono nella sezione "Materiali"
```

Basta aggiungere una nuova cartella o un nuovo `.md` e al push successivo compare nel sito.

## Anteprima in locale (opzionale)

```bash
pip install mkdocs-material
python build.py
mkdocs serve   # → http://localhost:8000
```
