#!/usr/bin/env python3
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

MAX_ITEMS = 30
SOURCES = [
    ("NovaMovie", "https://r.jina.ai/https://novamovie.net/movies", "novamovie.net"),
    ("YesHD", "https://r.jina.ai/https://yeshd.net/movies/", "yeshd.net"),
]

YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
QUALITY_RE = re.compile(r"\b(4K|UHD|BluRay|WEB[- .]?DL|WEBRip|HDTS|HDTC|HDRip|HD|CAM|TS|SD)\b", re.I)
DETAIL_RE = re.compile(r"^[a-z0-9][a-z0-9._~-]*(?:-[a-z0-9._~-]+)*-(19\d{2}|20\d{2})$", re.I)

# Example line:
# [HD![Image 2: The Deputy (2026)](https://image.tmdb.org/...jpg) ## The Deputy (2026)](https://novamovie.net/the-deputy-2026 "The Deputy (2026)")
CARD_RE = re.compile(
    r"^\[(?P<prefix>[^!\n]{0,40})!\[Image\s+\d+:\s*(?P<imgtitle>.*?)\]"
    r"\((?P<poster>https?://[^)]+)\)\s*##\s*(?P<title>.*?)\]"
    r"\((?P<url>https?://(?P<host>[^/]+)/(?P<slug>[^\s)\"]+))(?:\s+\"[^\"]*\")?\)\s*$",
    re.I,
)


def fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 MovieAlertMetadataMonitor/1.0",
            "Accept": "text/plain",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode("utf-8", "replace")


def parse_listing(text, expected_host):
    items = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        match = CARD_RE.match(line)
        if not match:
            continue

        host = match.group("host").lower().split(":", 1)[0]
        if host != expected_host:
            continue

        slug = match.group("slug").strip("/")
        slug_match = DETAIL_RE.match(slug)
        if not slug_match or slug in seen:
            continue

        display = re.sub(r"\s+", " ", match.group("title")).strip()
        year_match = YEAR_RE.search(display)
        year = year_match.group(1) if year_match else slug_match.group(1)
        title = re.sub(r"\s*\((?:19|20)\d{2}\)\s*$", "", display).strip()
        if len(title) < 2:
            continue

        quality_match = QUALITY_RE.search(match.group("prefix") or "")
        items.append(
            {
                "source": "HollyMovieHD",
                "metadata_source": expected_host,
                "source_type": "movie",
                "title": title,
                "url": f"https://hollymoviehd.cc/{slug}/",
                "poster_url": match.group("poster").strip(),
                "year": year,
                "quality": quality_match.group(1) if quality_match else None,
            }
        )
        seen.add(slug)
        if len(items) >= MAX_ITEMS:
            break
    return items


def build_cache():
    errors = []
    for source_name, reader_url, host in SOURCES:
        try:
            text = fetch_text(reader_url)
            items = parse_listing(text, host)
            if items:
                return {
                    "source": "HollyMovieHD",
                    "metadata_source": source_name,
                    "source_url": "https://hollymoviehd.cc/movies/",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "items": items,
                }
            errors.append(f"{source_name}: parsed 0 items")
        except Exception as exc:
            errors.append(f"{source_name}: {type(exc).__name__}")
    raise RuntimeError("; ".join(errors) or "No public mirror metadata available")


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else "holly_cache.json"
    payload = build_cache()
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(
        f"Built HollyMovieHD cache from {payload['metadata_source']} with {len(payload['items'])} items"
    )
    for item in payload["items"][:10]:
        print(f"- {item['title']} ({item['year']}) {item['quality'] or 'N/A'}")


if __name__ == "__main__":
    main()
