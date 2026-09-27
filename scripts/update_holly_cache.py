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
SPECIAL = {
    '', 'home', 'movies', 'series', 'recommended', 'most-viewed', 'request',
    'login', 'register', 'contact', 'dmca', 'privacy-policy', 'terms', 'about',
}
LINK_RE = re.compile(r'\[([^\]]*)\]\((https://hollymoviehd\.cc/[^\s)]+)(?:\s+"[^"]*")?\)', re.I)
IMAGE_RE = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)(?:\s+"[^"]*")?\)', re.I)
YEAR_RE = re.compile(r'\b(19\d{2}|20\d{2})\b')
QUALITY_RE = re.compile(r'\b(4K|UHD|BluRay|WEB[- .]?DL|WEBRip|HDTS|HDTC|HDRip|HD|CAM|TS|SD)\b', re.I)


def is_detail(url):
    p = urlparse(url)
    if p.netloc.lower() not in ('hollymoviehd.cc', 'www.hollymoviehd.cc'):
        return False
    parts = [x for x in p.path.split('/') if x]
    return len(parts) == 1 and parts[0].lower() not in SPECIAL


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
    window = text[max(0, start - 700):start]
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
        url = 'https://hollymoviehd.cc/' + p.path.strip('/') + '/'
        if url in seen:
            continue
        title = clean_title(label, url)
        if len(title) < 2:
            continue
        context = markdown[max(0, m.start() - 220):min(len(markdown), m.end() + 220)]
        ym = YEAR_RE.search(label + ' ' + context)
        qm = QUALITY_RE.search(context)
        out.append({
            'source': 'HollyMovieHD',
            'source_type': 'movie',
            'title': title,
            'url': url,
            'poster_url': nearby_poster(markdown, m.start()),
            'year': ym.group(1) if ym else None,
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
        raise SystemExit('No HollyMovieHD items parsed from public reader')
    payload = {
        'source': 'HollyMovieHD',
        'source_url': TARGET,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'items': items,
    }
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f'Parsed {len(items)} HollyMovieHD items')
    for item in items[:5]:
        print(f"- {item['title']} ({item.get('year') or 'N/A'}) {item['url']}")


if __name__ == '__main__':
    main()
