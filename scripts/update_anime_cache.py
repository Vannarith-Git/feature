#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

FEEDS = [
    ("Crunchyroll", "https://www.justwatch.com/id/provider/crunchyroll/new/tv-shows", "series", True),
    ("Crunchyroll", "https://www.justwatch.com/id/provider/crunchyroll/new/movies", "movie", True),
    ("Netflix", "https://www.justwatch.com/id/provider/netflix/new/tv-shows?genres=ani", "series", False),
    ("Netflix", "https://www.justwatch.com/id/provider/netflix/new/movies?genres=ani", "movie", False),
]
MAX_PER_FEED = 12
MAX_RESULTS = 60
MAX_HISTORY = 300
LINK_RE = re.compile(
    r"\[!\[Image\s+\d+:\s*(?P<title>.*?)\]\((?P<poster>https://images\.justwatch\.com/[^)]+)\)\]"
    r"\((?P<url>https://www\.justwatch\.com/id/(?P<kind>movie|tv-show)/[^)\s]+)\)",
    re.I,
)
QUALITY_RE = re.compile(r"\b(4K|UHD|Full\s*HD|1080p|HD)\b", re.I)


def fetch_text(url):
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": "Mozilla/5.0 MovieAlertAnimeMonitor/1.0", "Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8", "replace")


def candidates(provider, url, source_type):
    text = fetch_text(url)
    out, seen = [], set()
    for m in LINK_RE.finditer(text):
        item_url = m.group("url").rstrip("/)")
        if item_url in seen:
            continue
        seen.add(item_url)
        out.append({
            "provider": provider,
            "source_type": source_type,
            "title": re.sub(r"\s+", " ", m.group("title")).strip(),
            "url": item_url,
            "poster_url": m.group("poster"),
        })
        if len(out) >= MAX_PER_FEED:
            break
    return out


def field(text, heading):
    m = re.search(rf"###\s+{re.escape(heading)}\s*\n+([^\n]+)", text, re.I)
    return m.group(1).strip() if m else ""


def parse_detail(text, base, trusted_anime_provider=False):
    country = field(text, "Production country")
    genres = field(text, "Genres")
    low_genres = genres.lower()
    low_country = country.lower()

    if not trusted_anime_provider:
        # Netflix's animation catalogue also contains western animation. Keep
        # this source focused on Japanese anime.
        if "japan" not in low_country or not any(k in low_genres for k in ("animation", "anime")):
            return None
    else:
        # Crunchyroll is anime-focused. Keep animation/donghua titles, while
        # allowing entries whose JustWatch genre metadata is incomplete.
        if genres and not any(k in low_genres for k in ("animation", "anime", "action", "fantasy", "comedy", "drama")):
            return None

    heading = re.search(r"^#\s+(.+?)(?:\s+\((19\d{2}|20\d{2})\))?\s*$", text, re.M)
    title = base.get("title") or ""
    year = None
    if heading:
        title = heading.group(1).strip()
        year = heading.group(2)

    quality = None
    qm = QUALITY_RE.search(text[:6000])
    if qm:
        q = qm.group(1).upper().replace(" ", "")
        quality = "1080p" if q in ("FULLHD", "1080P") else q

    return {
        "source": "Anime",
        "source_type": base.get("source_type") or "series",
        "title": title,
        "url": base["url"],
        "poster_url": base.get("poster_url"),
        "year": year,
        "quality": quality,
        "category": "Anime" + (f" · {genres}" if genres else ""),
        "country": country,
    }


def load_previous(path):
    if not path or not os.path.exists(path):
        return {"candidate_results": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"candidate_results": {}}
    except Exception:
        return {"candidate_results": {}}


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "anime_cache.json"
    previous_path = sys.argv[2] if len(sys.argv) > 2 else ""
    previous = load_previous(previous_path)
    history = dict(previous.get("candidate_results") or {})

    all_candidates = {}
    feed_errors = []
    trusted = {}
    for provider, url, source_type, trusted_provider in FEEDS:
        try:
            for row in candidates(provider, url, source_type):
                entry = all_candidates.setdefault(row["url"], {**row, "providers": []})
                if provider not in entry["providers"]:
                    entry["providers"].append(provider)
                trusted[row["url"]] = trusted.get(row["url"], False) or trusted_provider
        except Exception as exc:
            feed_errors.append(f"{provider}/{source_type}: {type(exc).__name__}")

    now = datetime.now(timezone.utc).isoformat()
    items = []
    for url, candidate in all_candidates.items():
        cached = history.get(url)
        if cached is None:
            try:
                detail = fetch_text(url)
                parsed = parse_detail(detail, candidate, trusted.get(url, False))
                cached = {"match": bool(parsed), "item": parsed, "checked_at": now}
            except Exception as exc:
                cached = {"match": False, "item": None, "checked_at": now, "error": type(exc).__name__}
            history[url] = cached
        if cached.get("match") and cached.get("item"):
            item = dict(cached["item"])
            item["providers"] = candidate.get("providers", [])
            item["provider"] = ", ".join(item["providers"])
            items.append(item)

    active_urls = list(all_candidates.keys())
    extra_urls = [u for u in reversed(list(history.keys())) if u not in all_candidates]
    keep = set((active_urls + extra_urls)[:MAX_HISTORY])
    history = {u: history[u] for u in history if u in keep}

    items.sort(key=lambda x: x.get("title", "").lower())
    payload = {
        "source": "Anime",
        "source_url": "https://www.justwatch.com/id/provider/crunchyroll/new",
        "generated_at": now,
        "providers": sorted({p for p, _, _, _ in FEEDS}),
        "feed_errors": feed_errors,
        "items": items[:MAX_RESULTS],
        "candidate_results": history,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Anime cache: {len(payload['items'])} titles from {len(all_candidates)} candidates")
    if feed_errors:
        print("Feed warnings: " + "; ".join(feed_errors))
    for item in payload["items"][:12]:
        print(f"- {item['title']} ({item.get('year') or 'N/A'}) — {item.get('provider') or 'Unknown'}")


if __name__ == "__main__":
    main()
