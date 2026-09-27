import asyncio
import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import app as core

log = logging.getLogger("movie-bot")

_original_enrich = core.Scraper.enrich


def _parse_publish_date(value, tz_name=None):
    if not value:
        return None
    tz = ZoneInfo(tz_name or core.TIMEZONE)
    raw = str(value).strip()
    try:
        if len(raw) == 10 and raw[4] == '-' and raw[7] == '-':
            return date.fromisoformat(raw)
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz).date()
    except Exception:
        return None


def is_published_today(item, now=None):
    tz = ZoneInfo(core.TIMEZONE)
    local_now = now or datetime.now(tz)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=tz)
    published = _parse_publish_date(getattr(item, 'published_date', None), core.TIMEZONE)
    return published == local_now.astimezone(tz).date()


def _jsonld_date_published(node):
    if isinstance(node, dict):
        value = node.get('datePublished')
        if value:
            return str(value).strip()
        for child in node.values():
            found = _jsonld_date_published(child)
            if found:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _jsonld_date_published(child)
            if found:
                return found
    return None


async def enrich_with_publish_date(self, item):
    item = await _original_enrich(self, item)
    if getattr(item, 'published_date', None):
        return item

    # KhDiaMonD is WordPress/Dooplay based. Read the site's article publication
    # timestamp, never the movie's theatrical release year.
    if item.source != 'KhDiaMonD':
        return item
    try:
        s = await self.soup(item.url)
        meta = s.select_one(
            'meta[property="article:published_time"],'
            'meta[name="article:published_time"],'
            'meta[itemprop="datePublished"]'
        )
        if meta:
            raw = meta.get('content') or meta.get('datetime')
            if raw:
                item.published_date = str(raw).strip()
                return item

        for script in s.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or script.get_text() or '{}')
            except Exception:
                continue
            raw = _jsonld_date_published(data)
            if raw:
                item.published_date = raw
                return item
    except Exception as exc:
        log.warning('Could not read publication date for %s: %s', item.url, type(exc).__name__)
    return item


async def run_once_today_only(self):
    if self.lock.locked():
        return {'status': 'skipped', 'reason': 'run_in_progress'}

    async with self.lock:
        items, errors = await self.collect()
        first = self.db.get_state('initialized') != '1'
        if first and core.SEED_ON_FIRST_RUN:
            if not items:
                return {'status': 'source_unavailable', 'fetched': 0, 'errors': errors}
            for item in items:
                self.db.add(item, False)
            self.db.set_state('initialized', '1')
            return {'status': 'seeded', 'fetched': len(items), 'sent': 0, 'errors': errors}

        new_items = [item for item in items if not self.db.has_url(item.url)]
        if not core.TELEGRAM_BOT_TOKEN or not core.TELEGRAM_CHAT_ID:
            return {
                'status': 'waiting_for_telegram',
                'fetched': len(items),
                'pending_new': len(new_items),
                'sent': 0,
                'errors': errors,
            }

        tg = core.Telegram()
        sent = 0
        blocked_old = 0
        blocked_unknown_date = 0
        try:
            for item in reversed(new_items):
                item = await self.scraper.enrich(item)
                published = _parse_publish_date(getattr(item, 'published_date', None), core.TIMEZONE)
                if published is None:
                    self.db.add(item, False)
                    blocked_unknown_date += 1
                    log.info('Blocked notification without publish date: %s | %s', item.source, item.title)
                    continue
                if not is_published_today(item):
                    self.db.add(item, False)
                    blocked_old += 1
                    log.info('Blocked old publication %s: %s | %s', published, item.source, item.title)
                    continue

                await tg.send(item)
                self.db.add(item, True)
                sent += 1
        finally:
            await tg.close()

        self.db.set_state('initialized', '1')
        return {
            'status': 'ok',
            'fetched': len(items),
            'new': len(new_items),
            'eligible_today': sent,
            'sent': sent,
            'blocked_old': blocked_old,
            'blocked_unknown_date': blocked_unknown_date,
            'errors': errors,
        }


core.Scraper.enrich = enrich_with_publish_date
core.Service.run_once = run_once_today_only
