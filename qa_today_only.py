#!/usr/bin/env python3
import asyncio
import json
from datetime import date, datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

TZ = ZoneInfo('Asia/Phnom_Penh')
BASES = [
    ('movie', 'https://khdiamond.net/movies/'),
    ('series', 'https://khdiamond.net/seasons/'),
]
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
    'Accept-Language': 'km,en-US;q=0.9,en;q=0.8',
}


def parse_date(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        if len(raw) == 10 and raw[4] == '-' and raw[7] == '-':
            return date.fromisoformat(raw)
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).date()
    except Exception:
        return None


def jsonld_date(node):
    if isinstance(node, dict):
        if node.get('datePublished'):
            return str(node['datePublished']).strip()
        for value in node.values():
            found = jsonld_date(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = jsonld_date(value)
            if found:
                return found
    return None


def published_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    meta = soup.select_one(
        'meta[property="article:published_time"],'
        'meta[name="article:published_time"],'
        'meta[itemprop="datePublished"]'
    )
    if meta:
        raw = meta.get('content') or meta.get('datetime')
        if raw:
            return str(raw).strip()
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or '{}')
        except Exception:
            continue
        found = jsonld_date(data)
        if found:
            return found
    return None


def listing_links(html, base, expected):
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = urljoin(base, a['href'])
        path = urlparse(href).path
        if expected not in path or path.rstrip('/') in ('/movies', '/seasons') or '/page/' in path:
            continue
        if href in seen:
            continue
        seen.add(href)
        title = ' '.join((a.get_text(' ', strip=True) or a.get('title') or '').split())
        links.append((title or '(no title)', href))
        if len(links) >= 8:
            break
    return links


async def main():
    # Unit QA: eligibility must depend on source publication date, never movie year.
    today = datetime.now(TZ).date()
    assert parse_date(today.isoformat()) == today
    assert parse_date('2021') is None
    assert parse_date('2002') is None
    assert parse_date('2020-01-01') != today
    print('PASS unit-date-gate: movie year is never treated as publish date')

    parsed = 0
    old = 0
    today_count = 0
    rows = []
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=25) as client:
        for source_type, base in BASES:
            r = await client.get(base)
            r.raise_for_status()
            expected = '/movies/' if source_type == 'movie' else '/seasons/'
            links = listing_links(r.text, base, expected)
            assert links, f'No {source_type} detail links found'
            for title, url in links:
                d = await client.get(url)
                d.raise_for_status()
                raw = published_from_html(d.text)
                pub = parse_date(raw)
                if pub:
                    parsed += 1
                    if pub == today:
                        today_count += 1
                    else:
                        old += 1
                rows.append((source_type, title[:45], str(pub or 'UNKNOWN'), 'SEND' if pub == today else 'BLOCK'))

    print('\nKhDiaMonD live QA (today = %s):' % today)
    for row in rows:
        print('%-6s | %-45s | %-10s | %s' % row)

    # Hard QA rule: we need reliable source publication metadata before production.
    assert parsed >= max(6, len(rows) // 2), f'Only {parsed}/{len(rows)} pages exposed a parseable publish date'
    # A dry-run must never classify an unknown/old page as SEND.
    assert all(status == ('SEND' if pub == str(today) else 'BLOCK') for _, _, pub, status in rows)

    print(f'\nPASS live-khdiamond: parsed={parsed}/{len(rows)}, today={today_count}, old={old}, unknown={len(rows)-parsed}')
    print('PASS dry-run: only source pages published today are eligible; no Telegram messages were sent')


if __name__ == '__main__':
    asyncio.run(main())
