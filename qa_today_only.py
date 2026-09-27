#!/usr/bin/env python3
import asyncio
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

TZ = ZoneInfo('Asia/Phnom_Penh')
FEEDS = [
    ('movie', 'https://khdiamond.net/feed/?post_type=movies'),
    ('series', 'https://khdiamond.net/feed/?post_type=tvshows'),
]
HEADERS = {'User-Agent': 'Mozilla/5.0 MovieAlertQA/1.0'}


def parse_date(value):
    if not value:
        return None
    raw = str(value).strip()
    try:
        if len(raw) == 10 and raw[4] == '-' and raw[7] == '-':
            return date.fromisoformat(raw)
        try:
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError:
            dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ).date()
    except Exception:
        return None


async def main():
    today = datetime.now(TZ).date()

    # Unit QA: release years can never become publication dates.
    assert parse_date(today.isoformat()) == today
    assert parse_date('2021') is None
    assert parse_date('2002') is None
    assert parse_date('2020-01-01') != today
    print('PASS unit-date-gate: movie year is never treated as publish date')

    rows = []
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=25) as client:
        for source_type, feed_url in FEEDS:
            response = await client.get(feed_url)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            items = root.findall('./channel/item')
            assert items, f'No RSS items for {source_type}'
            for node in items[:10]:
                title = (node.findtext('title') or '').strip()
                url = (node.findtext('link') or '').strip()
                raw = (node.findtext('pubDate') or '').strip()
                pub = parse_date(raw)
                assert title and url and pub, f'Missing authoritative RSS metadata for {source_type}'
                status = 'SEND' if pub == today else 'BLOCK'
                rows.append((source_type, title[:48], str(pub), status))

    print(f'\nKhDiaMonD RSS QA — Cambodia today = {today}')
    for row in rows:
        print('%-6s | %-48s | %-10s | %s' % row)

    # Safety invariant: only the RSS pubDate equal to Cambodia's current date can send.
    for _, _, pub, status in rows:
        assert status == ('SEND' if pub == str(today) else 'BLOCK')

    eligible = sum(1 for *_, status in rows if status == 'SEND')
    blocked = len(rows) - eligible
    print(f'\nPASS live-rss: checked={len(rows)}, eligible_today={eligible}, blocked_old={blocked}')
    print('PASS dry-run: no Telegram message sent; old RSS posts are blocked')


if __name__ == '__main__':
    asyncio.run(main())
