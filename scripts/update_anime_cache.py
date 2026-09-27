#!/usr/bin/env python3
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

RANKING_URL = (
    "https://www.iq.com/wiki/id_id/ranking?channel=4&sort=4&"
    "type=1425950065128833%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B%3B"
)
MAX_RESULTS = 30
CARD_RE = re.compile(
    r"\[!\[Image\s+\d+:\s*Poster\s+(?P<title>.*?)\]"
    r"\((?P<proxy>https://www\.iq\.com/wiki/_next/image\?url=[^)]+)\)\]"
    r"\((?P<url>https://www\.iq\.com/play/[^)\s]+)\)",
    re.I,
)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\s*·")


def fetch_text(url):
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": "Mozilla/5.0 MovieAlertAnimeMonitor/2.0", "Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", "replace")


def poster_from_proxy(proxy):
    try:
        parsed = urllib.parse.urlparse(proxy)
        value = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
        return value or proxy
    except Exception:
        return proxy


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "anime_cache.json"
    text = fetch_text(RANKING_URL)
    matches = list(CARD_RE.finditer(text))
    items, seen = [], set()

    for idx, m in enumerate(matches):
        url = m.group("url").replace("&amp;", "&")
        if url in seen:
            continue
        seen.add(url)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else min(len(text), m.end() + 700)
        block = text[m.end():end]
        ym = YEAR_RE.search(block)
        title = re.sub(r"\s+", " ", m.group("title")).strip()
        if not title:
            continue
        items.append({
            "source": "Anime",
            "source_type": "series",
            "title": title,
            "url": url,
            "poster_url": poster_from_proxy(m.group("proxy")),
            "year": ym.group(1) if ym else None,
            "quality": None,
            "category": "Anime · iQIYI",
            "country": "Japan / China",
            "provider": "iQIYI",
            "providers": ["iQIYI"],
        })
        if len(items) >= MAX_RESULTS:
            break

    if not items:
        raise SystemExit("No iQIYI Anime cards parsed")

    payload = {
        "source": "Anime",
        "source_url": RANKING_URL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "providers": ["iQIYI"],
        "feed_errors": [],
        "items": items,
        "candidate_results": {i["url"]: {"match": True, "item": i} for i in items},
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Anime cache: {len(items)} latest iQIYI titles")
    for item in items[:12]:
        print(f"- {item['title']} ({item.get('year') or 'N/A'})")


if __name__ == "__main__":
    main()
