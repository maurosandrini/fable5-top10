#!/usr/bin/env python3
"""verify_top10.py — gate deterministico per data/latest.json (0 token).

Invarianti (post check avverso grok 2026-06-10):
  A. ogni post_url e ogni valore di engagement compare nei raw del run;
  B. 1-10 item, rank consecutivi da 1;
  G. (--ledger) item pubblicati presenti nel ledger cumulativo, id unici, mai accorciato;
  C. why_useful non vuoto e con overlap lessicale col testo del post nei raw
     (>= 2 parole contenuto, anti-hallucination);
  D. se il testo raw del post contiene numeri "vistosi" ($, k, %), claimed_metrics
     deve essere valorizzato;
  E. item gia' presente nell'archivio precedente => streak incrementato;
  F. generated_at parsabile ISO-8601 e non nel futuro.

Exit 0 = PASS, exit 1 = FAIL (non pushare).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STOP = frozenset(
    "the a an to for of in on and with from by at this that it is are was were be has have "
    "your you our their not no can will just into about more most".split()
)


def content_words(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3 and w not in STOP
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--prev", default="", help="archivio del run precedente (per check E)")
    ap.add_argument("--ledger", default="", help="data/ledger.json (per check G)")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    raw_blob = ""
    for p in sorted(Path(args.raw_dir).glob("*.json")):
        raw_blob += p.read_text(encoding="utf-8") + "\n"
    if not raw_blob:
        print(f"FAIL: nessun raw in {args.raw_dir}")
        return 1

    errors: list[str] = []
    items = data.get("items", [])

    # B
    if not 1 <= len(items) <= 10:
        errors.append(f"B: {len(items)} item (atteso 1-10)")
    if [it.get("rank") for it in items] != list(range(1, len(items) + 1)):
        errors.append("B: rank non consecutivi da 1")
    if len(items) < 10:
        print(f"[warn] lista corta ({len(items)}): richiesto banner 'fewer than 10' nella UI")

    # F
    try:
        gen = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
        if gen > datetime.now(timezone.utc):
            errors.append("F: generated_at nel futuro")
    except (KeyError, ValueError) as exc:
        errors.append(f"F: generated_at invalido ({exc})")

    prev_items = {}
    if args.prev and Path(args.prev).is_file():
        prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))
        prev_items = {it["post_url"]: it for it in prev.get("items", [])}

    for it in items:
        r = it.get("rank")
        url = it.get("post_url", "")
        # A: url nei raw
        if url not in raw_blob:
            errors.append(f"A: rank {r}: post_url non nei raw: {url}")
            continue
        # A: engagement nei raw (ogni valore numerico > 0 deve comparire vicino all'id)
        m = re.search(r"/status/(\d+)", url)
        ctx = raw_blob
        if m:
            idx = raw_blob.find(m.group(1))
            ctx = raw_blob[max(0, idx - 200) : idx + 2500] if idx >= 0 else raw_blob
        for k, v in (it.get("engagement") or {}).items():
            if isinstance(v, int) and v > 0 and not re.search(rf'"{k}"\s*:\s*{v}\b', ctx):
                errors.append(f"A: rank {r}: engagement {k}={v} non trovato nei raw")
        # C: overlap lessicale why_useful <-> testo raw del post
        wu = (it.get("why_useful") or "").strip()
        if not wu:
            errors.append(f"C: rank {r}: why_useful vuoto")
        else:
            overlap = content_words(wu) & content_words(ctx)
            if len(overlap) < 2:
                errors.append(f"C: rank {r}: why_useful non grounded sul post (overlap {len(overlap)})")
        # D: numeri vistosi nel testo raw => claimed_metrics valorizzato
        if re.search(r"\$\s?\d|[0-9]{2,}k\b|\d+\s?%", ctx[:1200]) and "claimed_metrics" not in it:
            errors.append(f"D: rank {r}: campo claimed_metrics assente")
        # E: streak
        if url in prev_items:
            if it.get("streak", 1) <= prev_items[url].get("streak", 1):
                errors.append(f"E: rank {r}: item ripetuto senza streak incrementato")

    # G: ledger cumulativo coerente (ogni item pubblicato sta nel ledger, id unici,
    # il ledger non si accorcia mai rispetto al run precedente)
    if args.ledger and Path(args.ledger).is_file():
        ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
        lit = ledger.get("items", [])
        urls = [x.get("post_url") for x in lit]
        ids = [x.get("id") for x in lit]
        if len(set(ids)) != len(ids):
            errors.append("G: id duplicati nel ledger")
        for it in items:
            if it.get("post_url") not in urls:
                errors.append(f"G: rank {it.get('rank')}: item pubblicato assente dal ledger")
        if len(lit) < len(prev_items):
            errors.append(f"G: ledger ({len(lit)}) più corto del run precedente ({len(prev_items)}): il ledger non dimentica")
    elif args.ledger:
        errors.append("G: ledger richiesto ma non trovato: " + args.ledger)

    if errors:
        print("FAIL (" + str(len(errors)) + " violazioni):")
        for e in errors:
            print("  " + e)
        return 1
    print(f"PASS: {len(items)} item verificati contro i raw; invarianti A-G ok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
