#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

PROVIDERS = [
    ("Netflix", "netflix"),
    ("Prime Video", "amazon-prime-video"),
    ("Catchplay", "catchplay"),
    ("KlikFilm", "klikfilm"),
    ("Viu", "viu"),
]
MAX_PER_PROVIDER = 10
MAX_RESULTS = 40
MAX_HISTORY = 250
MOVIE_LINK_RE = re.compile(
    r"\[!\[Image\s+\d+:\s*(?P<title>.*?)\]\((?P<poster>https://images\.justwatch\.com/[^)]+)\)\]"
    r"\((?P<url>https://www\.justwatch\.com/id/movie/[^)\s]+)\)",
    re.I,
)
YEAR_RE = re.compile(r"^#\s+.*?\((19\d{2}|20\d{2})\)\s*$", re.M)
QUALITY_RE = re.compile(r"\b(4K|UHD|Full\s*HD|1080p|HD)\b", re.I)


def fetch_text(url):
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": "Mozilla/5.0 MovieAlertMetadataMonitor/1.0", "Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8", "replace")


def provider_candidates(provider_slug):
    url = f"https://www.justwatch.com/id/provider/{provider_slug}/new/movies?genres=hrr"
    text = fetch_text(url)
    out = []
    seen = set()
    for match in MOVIE_LINK_RE.finditer(text):
        movie_url = match.group("url").rstrip("/)")
        if movie_url in seen:
            continue
        seen.add(movie_url)
        out.append({
            "title": re.sub(r"\s+", " ", match.group("title")).strip(),
            "url": movie_url,
            "poster_url": match.group("poster"),
        })
        if len(out) >= MAX_PER_PROVIDER:
            break
    return out


def parse_detail(text, base):
    lower = text.lower()
    country_match = re.search(r"###\s+Production country\s*\n+([^\n]+)", text, re.I)
    country = country_match.group(1).strip() if country_match else ""
    genres_match = re.search(r"###\s+Genres\s*\n+([^\n]+)", text, re.I)
    genres = genres_match.group(1).strip() if genres_match else ""
    if country.lower() != "indonesia":
        return None
    if not any(word in genres.lower() for word in ("horror", "mystery", "thriller")):
        return None

    heading = re.search(r"^#\s+(.+?)(?:\s+\((19\d{2}|20\d{2})\))?\s*$", text, re.M)
    title = base.get("title") or ""
    year = None
    if heading:
        title = heading.group(1).strip()
        year = heading.group(2)
    if not year:
        ym = YEAR_RE.search(text)
        year = ym.group(1) if ym else None

    quality = None
    qm = QUALITY_RE.search(text[:5000])
    if qm:
        q = qm.group(1).upper().replace(" ", "")
        quality = "1080p" if q in ("FULLHD", "1080P") else q

    return {
        "source": "Indonesian Horror",
        "source_type": "movie",
        "title": title,
        "url": base["url"],
        "poster_url": base.get("poster_url"),
        "year": year,
        "quality": quality,
        "category": genres,
        "country": country,
    }


def load_previous(path):
    if not path or not os.path.exists(path):
        return {"candidate_results": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"candidate_results": {}}


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "indonesia_horror_cache.json"
    previous_path = sys.argv[2] if len(sys.argv) > 2 else ""
    previous = load_previous(previous_path)
    history = dict(previous.get("candidate_results") or {})

    candidates = {}
    provider_errors = []
    for provider_name, provider_slug in PROVIDERS:
        try:
            rows = provider_candidates(provider_slug)
            for row in rows:
                entry = candidates.setdefault(row["url"], {**row, "providers": []})
                if provider_name not in entry["providers"]:
                    entry["providers"].append(provider_name)
        except Exception as exc:
            provider_errors.append(f"{provider_name}: {type(exc).__name__}")

    now = datetime.now(timezone.utc).isoformat()
    items = []
    for url, candidate in candidates.items():
        cached = history.get(url)
        if cached is None:
            try:
                detail = fetch_text(url)
                parsed = parse_detail(detail, candidate)
                cached = {"match": bool(parsed), "item": parsed, "checked_at": now}
            except Exception as exc:
                cached = {"match": False, "item": None, "checked_at": now, "error": type(exc).__name__}
            history[url] = cached

        if cached.get("match") and cached.get("item"):
            item = dict(cached["item"])
            item["providers"] = candidate.get("providers", [])
            item["provider"] = ", ".join(item["providers"])
            items.append(item)

    # Keep only recent candidate classifications so the cache remains compact.
    active_urls = list(candidates.keys())
    extra_urls = [u for u in reversed(list(history.keys())) if u not in candidates]
    keep = set((active_urls + extra_urls)[:MAX_HISTORY])
    history = {u: history[u] for u in history if u in keep}

    items.sort(key=lambda x: x.get("title", "").lower())
    payload = {
        "source": "Indonesian Horror",
        "source_url": "https://www.justwatch.com/id/movies",
        "generated_at": now,
        "providers": [name for name, _ in PROVIDERS],
        "provider_errors": provider_errors,
        "items": items[:MAX_RESULTS],
        "candidate_results": history,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Indonesian Horror cache: {len(payload['items'])} matching titles from {len(candidates)} horror candidates")
    if provider_errors:
        print("Provider warnings: " + "; ".join(provider_errors))
    for item in payload["items"][:12]:
        print(f"- {item['title']} ({item.get('year') or 'N/A'}) — {item.get('provider') or 'Unknown'}")


if __name__ == "__main__":
    main()
