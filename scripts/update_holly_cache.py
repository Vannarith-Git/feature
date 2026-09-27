#!/usr/bin/env python3
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

TARGET = 'https://hollymoviehd.cc/movies/'
READER = 'https://r.jina.ai/' + TARGET
MAX_ITEMS = 30
LINK_RE = re.compile(r'\[([^\]]*)\]\((https://hollymoviehd\.cc/[^\s)]+)(?:\s+"[^"]*")?\)', re.I)
IMAGE_RE = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)(?:\s+"[^"]*")?\)', re.I)
YEAR_RE = re.compile(r'\b(19\d{2}|20\d{2})\b')
QUALITY_RE = re.compile(r'\b(4K|UHD|BluRay|WEB[- .]?DL|WEBRip|HDTS|HDTC|HDRip|HD|CAM|TS|SD)\b', re.I)
MOVIE_SLUG_RE = re.compile(r'-(19\d{2}|20\d{2})$', re.I)


def is_detail(url):
    """Accept only Holly root-level movie URLs that end in a release year.

    Examples accepted: /dark-nuns-2025/, /heart-eyes-2025/.
    Navigation pages such as /anime/ or /top-movies/ are excluded.
    """
    p = urlparse(url)
    if p.netloc.lower() not in ('hollymoviehd.cc', 'www.hollymoviehd.cc'):
        return False
    parts = [x for x in p.path.split('/') if x]
    return len(parts) == 1 and bool(MOVIE_SLUG_RE.search(parts[0]))


def clean_title(label, url):
    label = re.sub(r'^Image:\s*', '', label or '', flags=re.I).replace('\\', '').strip()
    label = QUALITY_RE.sub('', label)
    label = re.sub(r'\s*\((?:19|20)\d{2}\)\s*$', '', label).strip(' -|')
    if len(label) >= 2 and label.lower() not in ('poster', 'image', 'watch now', 'details'):
        return label
    slug = urlparse(url).path.strip('/').replace('-', ' ')
    slug = re.sub(r'\s+(19\d{2}|20\d{2})$', '', slug)
    return ' '.join(w.capitalize() for w in slug.split())


def nearby_poster(text, start):
    window = text[max(0, start - 900):start]
    for image in reversed(IMAGE_RE.findall(window)):
        low = image.lower()
        if 'logo' not in low and ('wp-content' in low or re.search(r'\.(?:jpe?g|png|webp)(?:\?|$)', low)):
            return image
    return None


def fetch():
    req = urllib.request.Request(READER, headers={
        'User-Agent': 'Mozilla/5.0 MovieAlertMetadataMonitor/1.0',
        'Accept': 'text/plain',
    })
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read().decode('utf-8', 'replace')


def parse(markdown):
    out = []
    seen = set()
    for m in LINK_RE.finditer(markdown):
        label, raw_url = m.group(1), m.group(2).rstrip('.,;')
        if not is_detail(raw_url):
            continue

        p = urlparse(raw_url)
        slug = p.path.strip('/')
        url = 'https://hollymoviehd.cc/' + slug + '/'
        if url in seen:
            continue

        title = clean_title(label, url)
        if len(title) < 2:
            continue

        slug_year = MOVIE_SLUG_RE.search(slug)
        context = markdown[max(0, m.start() - 250):min(len(markdown), m.end() + 250)]
        qm = QUALITY_RE.search(context)
        year = slug_year.group(1) if slug_year else None

        out.append({
            'source': 'HollyMovieHD',
            'source_type': 'movie',
            'title': title,
            'url': url,
            'poster_url': nearby_poster(markdown, m.start()),
            'year': year,
            'quality': qm.group(1) if qm else None,
        })
        seen.add(url)
        if len(out) >= MAX_ITEMS:
            break
    return out


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else 'holly_cache.json'
    text = fetch()
    items = parse(text)
    if not items:
        raise SystemExit('No real HollyMovieHD movie URLs parsed from public reader')
    payload = {
        'source': 'HollyMovieHD',
        'source_url': TARGET,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'items': items,
    }
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'Parsed {len(items)} HollyMovieHD movie items')
    for item in items[:10]:
        print(f"- {item['title']} ({item.get('year') or 'N/A'}) {item['url']}")


if __name__ == '__main__':
    main()
