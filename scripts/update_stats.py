#!/usr/bin/env python3
"""Scarica i conteggi visite da GoatCounter e li salva in un JSON dentro il sito.

Con GOATCOUNTER_TOKEN nell'ambiente usa l'API autenticata (nessuna cache,
2 sole richieste); senza token ripiega sugli endpoint pubblici del visitor
counter (cache fino a 4 ore). Il sito legge il file dal proprio dominio,
così i numeri si vedono anche con gli ad-blocker.

Uso: python scripts/update_stats.py <destinazione/stats.json>
Se GoatCounter non risponde non scrive nulla ed esce 0: il sito ricade
sulle chiamate live.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CODE = "appunti-sspss"          # codice del sito su goatcounter.com
BASE_PATH = "/04_SSPSS/"        # percorso del sito su GitHub Pages
ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {".git", ".github", "docs", "site", "overrides", "Stage", "__pycache__", "scripts", "gh"}
TOKEN = os.environ.get("GOATCOUNTER_TOKEN", "").strip()


def subjects() -> list[str]:
    # NFC: i nomi di cartella salvati da macOS (NFD) devono combaciare con gli URL del browser
    return [unicodedata.normalize("NFC", d.name) for d in sorted(ROOT.iterdir())
            if d.is_dir() and d.name not in EXCLUDE_DIRS and not d.name.startswith(".")]


def to_int(value) -> int:
    return int(re.sub(r"\D", "", str(value)) or 0)


# ---------- API autenticata (fresca, 2 richieste) ----------

def api_get(endpoint: str, params: dict):
    url = (f"https://{CODE}.goatcounter.com/api/v0/{endpoint}?"
           + urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise RuntimeError(f"{endpoint} -> HTTP {e.code}: {body}") from None


def from_api():
    now = datetime.now(timezone.utc)
    span = {"start": "2020-01-01T00:00:00Z",
            "end": now.strftime("%Y-%m-%dT%H:00:00Z")}
    total = to_int(api_get("stats/total", span).get("total", 0))
    hits = api_get("stats/hits", {**span, "daily": "false", "limit": 100}).get("hits", [])
    by_path = {unicodedata.normalize("NFC", urllib.parse.unquote(h.get("path", ""))): to_int(h.get("count", 0)) for h in hits}
    paths = {}
    for name in subjects():
        p = BASE_PATH + name + "/"
        paths[p] = by_path.get(p, 0)
    return total, paths


# ---------- Endpoint pubblici (fallback, cache fino a 4h) ----------

def public_count(path: str):
    quoted = urllib.parse.quote(path, safe="/")
    variants = [quoted] if quoted == path else [quoted, path]
    missing = False
    for p in variants:
        url = f"https://{CODE}.goatcounter.com/counter/{urllib.parse.quote(p, safe='')}.json"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return to_int(json.load(r).get("count", 0))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                missing = True
                continue
            return None
        except Exception:
            return None
    return 0 if missing else None


def from_public():
    total = public_count("TOTAL")
    if total is None:
        return None
    paths = {}
    for name in subjects():
        p = BASE_PATH + name + "/"
        n = public_count(p)
        paths[p] = n if n is not None else 0
    return total, paths


def main():
    dest = Path(sys.argv[1])
    result = None
    source = "api"
    if TOKEN:
        try:
            result = from_api()
        except Exception as e:
            print(f"API non utilizzabile ({e}); provo gli endpoint pubblici")
    if result is None:
        source = "public"
        result = from_public()
    if result is None:
        print("GoatCounter non raggiungibile o counter pubblico disattivato: non scrivo nulla")
        return
    total, paths = result
    out = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "total": total,
        "paths": paths,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"stats.json scritto via {source}: total={total}, {len(paths)} materie")


if __name__ == "__main__":
    main()
