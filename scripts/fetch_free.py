#!/usr/bin/env python3
"""fetch_free.py — fetcher token-free per lo skill /radar-30-days.

Raccoglie segnali "ultimi N giorni" dalle fonti FREE e affidabili, li unifica,
li deduplica e li ordina per un rank che pesa rilevanza + freschezza + engagement
reale (upvote/punti/commenti/stelle) + qualità editoriale della fonte. ZERO token
Claude, ZERO API a pagamento.

Fonti coperte qui (token-free):
  - Hacker News  (Algolia API, public)
  - GitHub       (search repos + issues/PR; usa `gh api` se presente, sennò urllib; is:public)
  - Google News  (RSS, fonte editoriale/culturale; nessuna metrica di engagement)
  - Reddit       (best-effort .json; spesso 403 -> skippa con warning, mai blocca)

X/Twitter NON sta qui: a livello skill si usa l'MCP nativo mcp__x__* (no LLM-as-fetcher,
no reimplementazione di client). Questo script è puro stdlib: nessuna dipendenza esterna.

Pattern di scoring (engagement log1p -> weighted per fonte -> normalize 0-100;
rank = 0.60*rel + 0.20*freschezza + 0.10*engagement + 0.10*source_quality;
dedup ngram + token jaccard @0.7 con tokenizer che conserva le preposizioni contrastive)
ispirati a mvanhorn/last30days-skill (MIT), riscritti in forma snella.

Uso:
  python3 fetch_free.py --query "agentic engineering" --days 30 \
      --gh-extra-terms "llm,coding agent" --limit 30 --emit compact
  python3 fetch_free.py --query "claude code" --emit json > out.json

v0.3 (2026-06-09): hardening post review avversariale (GPT-5.5 xhigh + grok-build):
  guardrail input (query non vuota, days>=1, min-rel clamp [0,1], no fallback silenzioso),
  --gh-extra-terms in OR (query separate, non AND), post-filtro date Google News,
  dedupe che NON collassa "life with" vs "life after", SOURCE_QUALITY ora applicata,
  is:public su GitHub, source_counts nel meta.

v0.4 (2026-06-09): --profile <nome|path>: carica i default fetcher da
  profiles/<nome>.yaml (flat key: value, parser stdlib; la CLI esplicita ha
  SEMPRE precedenza). Le chiavi skill (x_handles*) non toccano il fetch: vengono
  riportate nel meta/stderr come promemoria per il Passo 2 (X via MCP).

v0.6 (2026-06-10): fonte substack via RSS per pubblicazione (--substack-pubs o
  chiave profilo substack_pubs); la search globale Substack richiede login
  (testata: 200 ma vuota senza sessione), quindi le pubblicazioni sono curate
  nel profilo come gli handle X. Description nel campo body per la rilevanza.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

USER_AGENT = "radar-30-days/0.6 (+codebase Mauro Sandrini; token-free research skill)"
HTTP_TIMEOUT = 20

# Pesi qualità editoriale per fonte (segnale/rumore). HN alto, social più rumoroso.
# Substack: newsletter curate dal profilo, sopra googlenews ma sotto HN.
SOURCE_QUALITY = {
    "hackernews": 0.80,
    "github": 0.82,
    "substack": 0.78,
    "googlenews": 0.72,
    "reddit": 0.60,
    "x": 0.68,
}

# Stopwords per la RILEVANZA: articoli/preposizioni + function-word che inquinano il match.
# "after/before/into..." sembrano semantiche ("life AFTER ai") ma matchano ovunque: tolte.
STOPWORDS = frozenset(
    "the a an to for how is in of on and with from by at this that it what are do can "
    "after before into about over vs your you my our their no not has have made "
    "il lo la i gli le un una di a da in con su per tra fra e che come".split()
)

# Per il DEDUP serve invece conservare le preposizioni contrastive: "life WITH ai" e
# "life AFTER ai" NON sono lo stesso item, e proprio quella differenza è il punto.
CONTRASTIVE = frozenset("with after before vs versus without against".split())
DEDUPE_STOPWORDS = STOPWORDS - CONTRASTIVE


# --------------------------------------------------------------------------- #
# HTTP                                                                         #
# --------------------------------------------------------------------------- #
def _get_json(url: str, headers: dict | None = None) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 - vogliamo degradare, mai crashare
        print(f"[warn] GET fallita {url[:80]}: {exc}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Fonti                                                                        #
# --------------------------------------------------------------------------- #
def fetch_hackernews(query: str, from_ts: int, min_points: int, limit: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "tags": "story",
            "numericFilters": f"created_at_i>{from_ts},points>{min_points}",
            "hitsPerPage": str(limit),
        }
    )
    data = _get_json(f"https://hn.algolia.com/api/v1/search?{params}")
    if not isinstance(data, dict):
        return []
    out = []
    for h in data.get("hits", []):
        created = h.get("created_at_i")
        out.append(
            {
                "source": "hackernews",
                "title": h.get("title") or h.get("story_title") or "",
                "url": h.get("url")
                or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "discussion_url": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "author": h.get("author"),
                "container": "Hacker News",
                "published_at": _ts_to_date(created),
                "engagement": {
                    "points": h.get("points") or 0,
                    "comments": h.get("num_comments") or 0,
                },
            }
        )
    return out


def _gh_api(path: str) -> dict | None:
    """GitHub API via `gh` (auth, rate alto) con fallback a urllib unauth."""
    if shutil.which("gh"):
        try:
            res = subprocess.run(
                ["gh", "api", path], capture_output=True, text=True, timeout=HTTP_TIMEOUT
            )
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout)
            # gh presente ma fallito (es. non loggato): silenzioso, si passa a urllib.
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] gh api eccezione: {exc}", file=sys.stderr)
    return _get_json(
        f"https://api.github.com/{path.lstrip('/')}",
        headers={"Accept": "application/vnd.github+json"},
    )


def _gh_repo(query: str, since: str, limit: int) -> list[dict]:
    # is:public per non far trapelare repo privati a cui il token `gh` ha accesso.
    q = urllib.parse.quote(f"{query} is:public pushed:>{since}")
    repos = _gh_api(f"search/repositories?q={q}&sort=stars&order=desc&per_page={limit}")
    rows = []
    for r in (repos or {}).get("items", []):
        rows.append(
            {
                "source": "github",
                "title": r.get("full_name", ""),
                "url": r.get("html_url"),
                "author": (r.get("owner") or {}).get("login"),
                "container": "GitHub repo",
                "body": r.get("description") or "",
                "published_at": (r.get("pushed_at") or "")[:10],
                "engagement": {
                    "stars": r.get("stargazers_count") or 0,
                    "forks": r.get("forks_count") or 0,
                },
            }
        )
    return rows


def fetch_github(query: str, since: str, extra_terms: list[str], limit: int) -> list[dict]:
    """Repos + issue/PR recenti. Gli extra-terms sono ALTERNATIVE (OR), non vincoli (AND):
    una query separata per il tema e per ciascun extra-term, poi si unisce."""
    out: list[dict] = []
    # OR: una ricerca repos per il tema principale e una per ciascun extra-term.
    per = max(5, limit // (1 + len(extra_terms)))
    for term in [query, *extra_terms]:
        out += _gh_repo(term, since, per)

    # Issue/PR: solo sul tema principale (evita di moltiplicare le chiamate).
    iq = urllib.parse.quote(f"{query} is:public created:>{since}")
    issues = _gh_api(f"search/issues?q={iq}&sort=reactions&order=desc&per_page={max(5, limit // 3)}")
    for it in (issues or {}).get("items", []):
        out.append(
            {
                "source": "github",
                "title": it.get("title", ""),
                "url": it.get("html_url"),
                "author": (it.get("user") or {}).get("login"),
                "container": "GitHub issue/PR",
                "body": (it.get("body") or "")[:300],
                "published_at": (it.get("created_at") or "")[:10],
                "engagement": {
                    "reactions": (it.get("reactions") or {}).get("total_count") or 0,
                    "comments": it.get("comments") or 0,
                },
            }
        )
    return out


def fetch_googlenews(query: str, max_days: int, limit: int) -> list[dict]:
    """Fonte editoriale free (Google News RSS). Forte sui temi culturali/sociali dove
    HN/GitHub sono ciechi. Nessuna metrica di engagement: rank su rilevanza + freschezza.
    Post-filtro temporale: `when:Nd` non è affidabile, quindi si scartano gli item con
    data oltre la finestra (gli item senza data si tengono ma con freschezza 0)."""
    params = urllib.parse.urlencode(
        {"q": f"{query} when:{max_days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    req = urllib.request.Request(
        f"https://news.google.com/rss/search?{params}", headers={"User-Agent": USER_AGENT}
    )
    out: list[dict] = []
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            root = ET.fromstring(resp.read())
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Google News RSS fallita: {exc}", file=sys.stderr)
        return out
    dropped = 0
    for it in root.findall(".//item")[: limit * 2]:
        pub = it.findtext("pubDate")
        try:
            date = parsedate_to_datetime(pub).date().isoformat() if pub else None
        except (TypeError, ValueError):
            date = None
        age = _days_ago(date)
        if age is not None and age > max_days:  # fuori finestra: scarta
            dropped += 1
            continue
        src_el = it.find("{*}source")
        out.append(
            {
                "source": "googlenews",
                "title": it.findtext("title") or "",
                "url": it.findtext("link"),
                "author": None,
                "container": src_el.text if src_el is not None else "Google News",
                "published_at": date,
                "engagement": {},
            }
        )
        if len(out) >= limit:
            break
    if dropped:
        print(f"[info] Google News: {dropped} item scartati fuori finestra {max_days}gg", file=sys.stderr)
    return out


def fetch_substack(pubs: list[str], max_days: int, limit: int) -> list[dict]:
    """Newsletter Substack via RSS per pubblicazione (free, token-free). La search
    globale di Substack richiede sessione autenticata (testata 2026-06-10: HTTP 200
    ma risultati sempre vuoti senza login), quindi le pubblicazioni arrivano dal
    profilo (`substack_pubs`), curate come gli handle X. Nessuna metrica di
    engagement pubblica nel feed: rank su rilevanza + freschezza. La description
    (spogliata dell'HTML) entra nel campo `body`, usato dalla rilevanza: i titoli
    delle newsletter spesso non contengono i termini della query."""
    out: list[dict] = []
    if not pubs:
        return out
    per = max(3, limit // len(pubs))
    for pub in pubs:
        host = pub.strip().strip("/")
        if not host:
            continue
        url = (host.rstrip("/") + "/feed") if host.startswith("http") else f"https://{host}/feed"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                root = ET.fromstring(resp.read())
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Substack RSS fallita {host}: {exc}", file=sys.stderr)
            continue
        feed_title = root.findtext(".//channel/title") or host
        dropped = taken = 0
        for it in root.findall(".//item"):
            pubdate = it.findtext("pubDate")
            try:
                date = parsedate_to_datetime(pubdate).date().isoformat() if pubdate else None
            except (TypeError, ValueError):
                date = None
            age = _days_ago(date)
            if age is not None and age > max_days:  # fuori finestra: scarta
                dropped += 1
                continue
            desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "").strip()[:400]
            out.append(
                {
                    "source": "substack",
                    "title": it.findtext("title") or "",
                    "url": it.findtext("link"),
                    "author": it.findtext("{http://purl.org/dc/elements/1.1/}creator"),
                    "container": feed_title,
                    "published_at": date,
                    "body": desc,
                    "engagement": {},
                }
            )
            taken += 1
            if taken >= per:
                break
        if dropped:
            print(f"[info] Substack {host}: {dropped} item fuori finestra {max_days}gg", file=sys.stderr)
    return out


def fetch_reddit(query: str, subreddits: list[str], max_days: int, limit: int) -> list[dict]:
    """Best-effort: il .json pubblico di Reddit risponde spesso 403. Mai blocca.
    La finestra `t` segue --days (week se <=7, month se <=31, sennò year)."""
    t = "week" if max_days <= 7 else "month" if max_days <= 31 else "year"
    out: list[dict] = []
    targets = subreddits or [""]
    for sub in targets:
        if sub:
            url = f"https://www.reddit.com/r/{sub}/search.json?" + urllib.parse.urlencode(
                {"q": query, "restrict_sr": "on", "sort": "top", "t": t, "limit": limit}
            )
        else:
            url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode(
                {"q": query, "sort": "top", "t": t, "limit": limit}
            )
        data = _get_json(url)
        if not isinstance(data, dict):
            continue
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            out.append(
                {
                    "source": "reddit",
                    "title": d.get("title", ""),
                    "url": f"https://www.reddit.com{d.get('permalink', '')}",
                    "author": d.get("author"),
                    "container": f"r/{d.get('subreddit', sub)}",
                    "published_at": _ts_to_date(d.get("created_utc")),
                    "engagement": {
                        "score": d.get("score") or 0,
                        "num_comments": d.get("num_comments") or 0,
                        "upvote_ratio": d.get("upvote_ratio") or 0,
                    },
                }
            )
    return out


# --------------------------------------------------------------------------- #
# Scoring                                                                      #
# --------------------------------------------------------------------------- #
def _ts_to_date(ts) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _log1p(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return math.log1p(v) if v > 0 else 0.0


def _days_ago(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (datetime.now(timezone.utc).date() - d).days
    except ValueError:
        return None


def freshness(date_str: str | None, max_days: int) -> int:
    age = _days_ago(date_str)
    if age is None:
        return 0
    if age <= 0:
        return 100
    if age >= max_days:
        return 0
    return int(100 * (1 - age / max_days))


def engagement_raw(item: dict) -> float | None:
    e = item.get("engagement") or {}
    s = item["source"]
    if s == "hackernews":
        val = 0.55 * _log1p(e.get("points")) + 0.45 * _log1p(e.get("comments"))
    elif s == "github":
        # pesi normalizzati a somma 1.0
        val = (
            0.50 * _log1p(e.get("stars"))
            + 0.15 * _log1p(e.get("forks"))
            + 0.20 * _log1p(e.get("reactions"))
            + 0.15 * _log1p(e.get("comments"))
        )
    elif s == "reddit":
        val = (
            0.50 * _log1p(e.get("score"))
            + 0.35 * _log1p(e.get("num_comments"))
            + 0.05 * (float(e.get("upvote_ratio") or 0) * 10.0)
        )
    else:
        vals = [x for v in e.values() if (x := _log1p(v)) > 0]
        val = sum(vals) / len(vals) if vals else 0.0
    return val or None


def _tokens(text: str, stop: frozenset = STOPWORDS) -> set[str]:
    norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()
    return {t for t in norm.split() if len(t) > 1 and t not in stop}


def relevance(item: dict, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 1.0
    text = " ".join(str(item.get(k) or "") for k in ("title", "body", "container"))
    it = _tokens(text)
    if not it:
        return 0.0
    return len(query_tokens & it) / len(query_tokens)


def _ngrams(text: str, n: int = 3) -> set[str]:
    norm = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()
    if len(norm) < n:
        return {norm} if norm else set()
    return {norm[i : i + n] for i in range(len(norm) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe(items: list[dict], threshold: float = 0.7) -> list[dict]:
    """Dedup near-duplicate. Usa un tokenizer che CONSERVA le preposizioni contrastive
    (with/after/...): così "life with ai" e "life after ai" non collassano nello stesso item."""
    kept: list[dict] = []
    prepared: list[tuple[set, set]] = []
    for it in items:
        text = f"{it.get('title', '')} {it.get('author') or ''}".strip()
        ng, tk = _ngrams(text), _tokens(text, DEDUPE_STOPWORDS)
        if any(
            max(_jaccard(ng, png), _jaccard(tk, ptk)) >= threshold for png, ptk in prepared
        ):
            continue
        kept.append(it)
        prepared.append((ng, tk))
    return kept


def normalize(values: list[float | None]) -> list[int | None]:
    valid = [v for v in values if v is not None]
    if not valid:
        return [None] * len(values)
    lo, hi = min(valid), max(valid)
    if math.isclose(lo, hi):
        return [50 if v is not None else None for v in values]
    return [None if v is None else int((v - lo) / (hi - lo) * 100) for v in values]


def rank_items(items: list[dict], query: str, max_days: int, min_rel: float = 0.0) -> list[dict]:
    qtok = _tokens(query)
    eng = normalize([engagement_raw(it) for it in items])
    for it, es in zip(items, eng):
        rel = relevance(it, qtok)
        fr = freshness(it.get("published_at"), max_days)
        sq = SOURCE_QUALITY.get(it["source"], 0.6)
        it["scores"] = {
            "relevance": round(rel, 3),
            "freshness": fr,
            "engagement": es,
            "engagement_known": bool(it.get("engagement")),
            "source_quality": sq,
        }
        it["days_ago"] = _days_ago(it.get("published_at"))
        it["rank"] = round(
            0.60 * rel + 0.20 * (fr / 100.0) + 0.10 * ((es or 0) / 100.0) + 0.10 * sq, 4
        )
    ranked = sorted(items, key=lambda x: x["rank"], reverse=True)
    if min_rel > 0:
        # Cutoff anti-rumore: scarta i match deboli. NIENTE fallback silenzioso:
        # se nessun item supera la soglia, restituisce vuoto con warning esplicito.
        kept = [it for it in ranked if (it["scores"]["relevance"] or 0) >= min_rel]
        if not kept:
            print(f"[warn] nessun item supera --min-rel={min_rel}: output vuoto", file=sys.stderr)
        return kept
    return ranked


# --------------------------------------------------------------------------- #
# Profili dominio                                                              #
# --------------------------------------------------------------------------- #
# Chiavi del profilo che mappano su flag del fetcher (tipo incluso).
PROFILE_FETCH_KEYS = {
    "sources": ("--sources", str),
    "gh_extra_terms": ("--gh-extra-terms", str),
    "subreddits": ("--subreddits", str),
    "substack_pubs": ("--substack-pubs", str),
    "min_rel": ("--min-rel", float),
    "hn_min_points": ("--hn-min-points", int),
    "days": ("--days", int),
    "limit": ("--limit", int),
}


def load_profile(spec: str) -> dict[str, str]:
    """Parser flat `chiave: valore` (subset YAML, stdlib). Commenti con #, valori
    eventualmente quotati. Nessuna struttura annidata: i profili restano piatti."""
    p = Path(spec)
    if not p.is_file():
        p = Path(__file__).resolve().parent.parent / "profiles" / f"{spec}.yaml"
    if not p.is_file():
        raise FileNotFoundError(f"profilo '{spec}' non trovato (ne' come path ne' in profiles/)")
    prof: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        val = val.split(" #")[0].strip().strip("\"'")
        prof[key.strip()] = val
    return prof


def _flag_passed(flag: str) -> bool:
    return any(a == flag or a.startswith(flag + "=") for a in sys.argv[1:])


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="Fetcher token-free per /radar-30-days")
    ap.add_argument("--query", required=True, help="query principale")
    ap.add_argument(
        "--profile",
        default="",
        help="profilo dominio (nome in profiles/ o path yaml); la CLI esplicita prevale",
    )
    ap.add_argument("--days", type=int, default=30, help="finestra temporale (default 30)")
    ap.add_argument("--limit", type=int, default=30, help="risultati finali (default 30)")
    ap.add_argument("--hn-min-points", type=int, default=5)
    ap.add_argument("--gh-extra-terms", default="", help="termini extra GitHub (OR), separati da virgola")
    ap.add_argument("--subreddits", default="", help="subreddit, separati da virgola (best-effort)")
    ap.add_argument(
        "--substack-pubs",
        default="",
        help="pubblicazioni Substack (host o URL), separate da virgola; di solito dal profilo",
    )
    ap.add_argument(
        "--sources",
        default="hackernews,github,googlenews,substack",
        help="fonti attive (default: hackernews,github,googlenews,substack). "
        "substack richiede --substack-pubs o un profilo con substack_pubs; reddit è best-effort.",
    )
    ap.add_argument(
        "--min-rel",
        type=float,
        default=0.15,
        help="cutoff rilevanza anti-rumore (default 0.15; alza a 0.34+ per temi culturali/non-tech)",
    )
    ap.add_argument("--emit", choices=["json", "compact"], default="compact")
    args = ap.parse_args()

    # Profilo dominio: applica i default del profilo SOLO dove la CLI non e' esplicita.
    profile: dict[str, str] = {}
    if args.profile:
        try:
            profile = load_profile(args.profile)
        except (FileNotFoundError, OSError) as exc:
            ap.error(str(exc))
        for key, (flag, cast) in PROFILE_FETCH_KEYS.items():
            raw_val = profile.get(key, "")
            if not raw_val or _flag_passed(flag):
                continue
            try:
                setattr(args, flag.lstrip("-").replace("-", "_"), cast(raw_val))
            except ValueError:
                print(f"[warn] profilo {profile.get('name', args.profile)}: "
                      f"valore '{raw_val}' non valido per {key}, ignorato", file=sys.stderr)
        handles = ", ".join(v for v in (profile.get("x_handles"), profile.get("x_handles_candidati")) if v)
        if handles:
            print(f"[info] profilo '{profile.get('name', args.profile)}': handle X per il "
                  f"Passo 2 (MCP nativo): {handles}", file=sys.stderr)

    # Guardrail input (review avversariale 2026-06-09): meglio fallire chiaro che dare risultati assurdi.
    if not args.query or not args.query.strip():
        ap.error("--query non può essere vuota o solo spazi")
    if args.days < 1:
        ap.error("--days deve essere >= 1")
    if args.limit < 1:
        ap.error("--limit deve essere >= 1")
    if not 0.0 <= args.min_rel <= 1.0:
        clamped = min(1.0, max(0.0, args.min_rel))
        print(f"[warn] --min-rel {args.min_rel} fuori range [0,1]: uso {clamped}", file=sys.stderr)
        args.min_rel = clamped

    # Copertura X (Passo 2): la recent search dei wrapper MCP arriva a ~7gg indietro
    # e non espone start_time/end_time; oltre, servono le timeline degli handle.
    if args.days > 7:
        print(
            f"[info] finestra {args.days}gg: x_search_tweets copre solo ~7gg; per il resto "
            f"della finestra usare x_get_user_tweets sugli handle e filtrare per created_at "
            f"(Passo 2 SKILL.md)",
            file=sys.stderr,
        )

    from_ts = int(time.time()) - args.days * 86400
    since = datetime.fromtimestamp(from_ts, tz=timezone.utc).date().isoformat()
    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    extra = [t.strip() for t in args.gh_extra_terms.split(",") if t.strip()]
    subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]

    items: list[dict] = []
    if "hackernews" in sources:
        items += fetch_hackernews(args.query, from_ts, args.hn_min_points, args.limit)
    if "github" in sources:
        items += fetch_github(args.query, since, extra, args.limit)
    if "googlenews" in sources:
        items += fetch_googlenews(args.query, args.days, args.limit)
    if "substack" in sources:
        sspubs = [p.strip() for p in args.substack_pubs.split(",") if p.strip()]
        if sspubs:
            items += fetch_substack(sspubs, args.days, args.limit)
        else:
            print(
                "[info] substack attiva ma senza pubblicazioni: aggiungi substack_pubs "
                "al profilo o passa --substack-pubs",
                file=sys.stderr,
            )
    if "reddit" in sources:
        items += fetch_reddit(args.query, subs, args.days, args.limit)

    # Conteggio per-fonte PRIMA di dedup/rank (trasparenza: quale fonte ha reso quanto).
    raw_counts: dict[str, int] = {}
    for it in items:
        raw_counts[it["source"]] = raw_counts.get(it["source"], 0) + 1

    items = dedupe(items)
    items = rank_items(items, args.query, args.days, args.min_rel)[: args.limit]

    final_counts: dict[str, int] = {}
    for it in items:
        final_counts[it["source"]] = final_counts.get(it["source"], 0) + 1

    meta = {
        "query": args.query,
        "days": args.days,
        "x_coverage_days": min(args.days, 7),
        "from": since,
        "sources": sorted(sources),
        "profile": profile.get("name") if profile else None,
        "x_handles_hint": profile.get("x_handles") or None if profile else None,
        "min_rel": args.min_rel,
        "source_counts_raw": raw_counts,
        "source_counts_final": final_counts,
        "count": len(items),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    if args.emit == "json":
        print(json.dumps({"meta": meta, "items": items}, ensure_ascii=False, indent=2))
    else:
        print(f"# radar-30-days | {meta['query']} | ultimi {meta['days']}gg | {meta['count']} item")
        print(f"# fonti: {', '.join(meta['sources'])} | dal {meta['from']} | min-rel {meta['min_rel']}")
        print(f"# raccolti per fonte: {raw_counts}\n")
        for i, it in enumerate(items, 1):
            sc = it["scores"]
            eng = it.get("engagement", {})
            engstr = " ".join(f"{k}={v}" for k, v in eng.items()) or "n/a"
            print(
                f"{i:>2}. [{it['source']}] {it['title'][:80]}\n"
                f"    {it.get('url', '')}\n"
                f"    rank={it['rank']} (rel={sc['relevance']} fresh={sc['freshness']} "
                f"eng={sc['engagement']} sq={sc['source_quality']}) "
                f"| {it.get('days_ago', '?')}gg fa | {engstr}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
