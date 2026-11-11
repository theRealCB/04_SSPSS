#!/usr/bin/env python3
"""Scarica i conteggi visite da GoatCounter e li salva in un JSON dentro il sito.

Usato dalla GitHub Action a ogni deploy e dalla run notturna: il sito legge
i numeri dal proprio dominio, così si vedono anche con gli ad-blocker.
Uso: python scripts/update_stats.py <destinazione/stats.json>
Se GoatCounter non risponde (counter pubblico spento, nessuna visita, rete),
non scrive nulla ed esce 0: il sito ricade sulle chiamate live.
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CODE = "appunti-sspss"          # codice del sito su goatcounter.com
BASE_PATH = "/04_SSPSS/"        # percorso del sito su GitHub Pages
ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".git", ".github", "docs", "site", "overrides", "Stage", "__pycache__", "scripts", "gh"}


def fetch_count(path: str):
    """Conteggio per un percorso; prova la variante così com'è e quella encodata. 404 = 0."""
    quoted = urllib.parse.quote(path, safe="/")
    variants = [quoted] if quoted == path else [quoted, path]
    missing = False
    for p in variants:
        url = f"https://{CODE}.goatcounter.com/counter/{urllib.parse.quote(p, safe='')}.json"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
                return int(re.sub(r"\D", "", str(data.get("count", "0"))) or 0)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                missing = True
                continue
            return None
        except Exception:
            return None
    return 0 if missing else None


def main():
    dest = Path(sys.argv[1])
    total = fetch_count("TOTAL")
    if total is None:
        print("GoatCounter non raggiungibile o counter pubblico disattivato: non scrivo nulla")
        return
    subjects = [d.name for d in sorted(ROOT.iterdir())
                if d.is_dir() and d.name not in EXCLUDE_DIRS and not d.name.startswith(".")]
    paths = {}
    for name in subjects:
        p = BASE_PATH + name + "/"
        n = fetch_count(p)
        paths[p] = n if n is not None else 0
    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": total,
        "paths": paths,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"stats.json scritto: total={total}, {len(paths)} materie")


if __name__ == "__main__":
    main()
