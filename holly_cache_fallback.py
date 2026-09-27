import json
import logging

import app as core

log = logging.getLogger('movie-bot')
CACHE_URL = 'https://raw.githubusercontent.com/Vannarith-Git/feature/holly-cache/holly_cache.json'

_original_holly = core.Scraper.holly
_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text


async def holly_with_github_cache(self):
    try:
        return await _original_holly(self)
    except Exception as upstream_error:
        try:
            response = await self.client.get(CACHE_URL)
            response.raise_for_status()
            payload = response.json()
            raw_items = payload.get('items') or []
            items = []
            for row in raw_items[:core.MAX_ITEMS]:
                title = str(row.get('title') or '').strip()
                url = str(row.get('url') or '').strip()
                if not title or not url.startswith('https://hollymoviehd.cc/'):
                    continue
                items.append(core.MovieItem(
                    'HollyMovieHD',
                    str(row.get('source_type') or 'movie'),
                    title,
                    url,
                    row.get('poster_url'),
                    row.get('year'),
                    row.get('quality'),
                ))
            if not items:
                raise RuntimeError('Holly cache is empty')
            self._holly_listing_url = CACHE_URL
            self._holly_mode = 'github-cache'
            self._holly_cache_generated_at = payload.get('generated_at')
            if getattr(self, '_holly_logged_mode', None) != 'github-cache':
                log.info(
                    'HollyMovieHD monitoring via GitHub metadata cache (%s items, generated_at=%s)',
                    len(items), payload.get('generated_at')
                )
                self._holly_logged_mode = 'github-cache'
            return items
        except Exception as cache_error:
            self._holly_mode = 'unavailable'
            raise RuntimeError(
                f'HollyMovieHD unavailable; cache={type(cache_error).__name__}; '
                f'upstream={type(upstream_error).__name__}'
            ) from cache_error


async def enrich_with_github_cache(self, item):
    if item.source == 'HollyMovieHD' and getattr(self, '_holly_mode', None) == 'github-cache':
        # Listing cache already contains the metadata available from Holly's public
        # page. Avoid blocked detail-page requests when operating from cache mode.
        return item
    return await _original_enrich(self, item)


async def bot_send_text_with_cache_status(text, chat_id=None):
    old = '⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403'
    scraper = getattr(getattr(core, 'service', None), 'scraper', None)
    if old in text and getattr(scraper, '_holly_mode', None) == 'github-cache':
        text = text.replace(old, '✅ HollyMovieHD — active via 5-minute public metadata cache')
    return await _original_bot_send_text(text, chat_id)


core.Scraper.holly = holly_with_github_cache
core.Scraper.enrich = enrich_with_github_cache
core.bot_send_text = bot_send_text_with_cache_status
