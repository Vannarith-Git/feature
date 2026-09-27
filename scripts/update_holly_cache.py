#!/usr/bin/env python3
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone

MAX_ITEMS = 30
TARGET = "https://hollymoviehd.cc/movies/"
READER_URL = "https://r.jina.ai/https://hollymoviehd.cc/movies/"

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
QUALITY_RE = re.compile(r"\b(4K|UHD|BluRay|WEB[- .]?DL|WEBRip|HDTS|HDTC|HDRip|HD|CAM|TS|SD)\b", re.I)
DETAIL_RE = re.compile(r"^[a-z0-9][a-z0-9._~-]*(?:-[a-z0-9._~-]+)*-(19\d{2}|20\d{2})$", re.I)
CARD_RE = re.compile(
    r"^\[(?P<prefix>[^!\n]{0,40})!\[Image\s+\d+:\s*(?P<imgtitle>.*?)\]"
    r"\((?P<poster>https?://[^)]+)\)\s*##\s*(?P<title>.*?)\]"
    r"\((?P<url>https://hollymoviehd\.cc/(?P<slug>[^\s)\"]+))(?:\s+\"[^\"]*\")?\)\s*$",
    re.I,
)


def fetch_text(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "MovieAlertMetadataMonitor/1.0",
        "Accept": "text/plain",
    })
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8", "replace")


def parse_listing(text):
    items, seen = [], set()
    for raw in text.splitlines():
        m = CARD_RE.match(raw.strip())
        if not m:
            continue
        slug = m.group("slug").strip("/")
        sm = DETAIL_RE.match(slug)
        if not sm or slug in seen:
            continue
        display = re.sub(r"\s+", " ", m.group("title")).strip()
        ym = YEAR_RE.search(display)
        year = ym.group(1) if ym else sm.group(1)
        title = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", display).strip()
        if len(title) < 2:
            continue
        qm = QUALITY_RE.search(m.group("prefix") or "")
        items.append({
            "source": "HollyMovieHD",
            "metadata_source": "Jina public reader",
            "source_type": "movie",
            "title": title,
            "url": f"https://hollymoviehd.cc/{slug}/",
            "poster_url": m.group("poster").strip(),
            "year": year,
            "quality": qm.group(1) if qm else None,
        })
        seen.add(slug)
        if len(items) >= MAX_ITEMS:
            break
    return items


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "holly_cache.json"
    items = parse_listing(fetch_text(READER_URL))
    if not items:
        raise SystemExit("No HollyMovieHD movie cards parsed from public reader")
    payload = {
        "source": "HollyMovieHD",
        "metadata_source": "Jina public reader",
        "source_url": TARGET,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Built HollyMovieHD cache with {len(items)} items via Jina public reader")
    for item in items[:10]:
        print(f"- {item['title']} ({item['year']}) {item['quality'] or 'N/A'}")


if __name__ == "__main__":
    main()
