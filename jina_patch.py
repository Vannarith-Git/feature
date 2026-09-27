import logging
import re

import app as core

log = logging.getLogger('movie-bot')

JINA_HOLLY_LISTING = 'https://r.jina.ai/https://hollymoviehd.cc/movies/'
_original_holly = core.Scraper.holly
_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text

# Example line returned by the public reader:
# [HD![Image 2: Title (2026)](https://image.tmdb.org/...jpg) ## Title (2026)](https://hollymoviehd.cc/title-2026/ "Title (2026)")
ITEM_RE = re.compile(
    r'^\[(?P<prefix>[^!\n]{0,40})!\[Image\s+\d+:\s*(?P<imgtitle>.*?)\]'
    r'\((?P<poster>https?://[^)]+)\)\s*##\s*(?P<title>.*?)\]'
    r'\((?P<url>https://hollymoviehd\.cc/[^\s)]+)(?:\s+"[^"]*")?\)\s*$',
    re.I,
)
DETAIL_RE = re.compile(r'^https://hollymoviehd\.cc/[a-z0-9][a-z0-9._~-]*(?:-[a-z0-9._~-]+)*-(?:19|20)\d{2}/?$', re.I)


def parse_jina_listing(text):
    items = []
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        m = ITEM_RE.match(line)
        if not m:
            continue
        url = m.group('url').rstrip('/') + '/'
        if not DETAIL_RE.match(url) or url in seen:
            continue

        display = re.sub(r'\s+', ' ', m.group('title')).strip()
        year_match = core.YEAR_RE.search(display) or core.YEAR_RE.search(url)
        year = year_match.group(1) if year_match else None
        title = re.sub(r'\s*\((?:19|20)\d{2}\)\s*$', '', display).strip()
        if len(title) < 2:
            continue

        prefix = m.group('prefix') or ''
        quality_match = core.QUALITY_RE.search(prefix)
        poster = m.group('poster').strip()

        items.append(core.MovieItem(
            source='HollyMovieHD',
            source_type='movie',
            title=title,
            url=url,
            poster_url=poster,
            year=year,
            quality=quality_match.group(1) if quality_match else None,
        ))
        seen.add(url)
        if len(items) >= core.MAX_ITEMS:
            break
    return items


async def holly_with_free_reader(self):
    try:
        result = await _original_holly(self)
        if result:
            self._holly_mode = 'direct'
            return result
    except Exception as direct_error:
        self._holly_direct_error = type(direct_error).__name__

    try:
        response = await self.client.get(JINA_HOLLY_LISTING, headers={
            'Accept': 'text/plain',
            'User-Agent': 'MovieAlertMetadataMonitor/1.0',
        })
        response.raise_for_status()
        items = parse_jina_listing(response.text)
        if not items:
            raise RuntimeError('Jina reader returned no Holly movie items')
        self._holly_mode = 'reader:jina'
        if getattr(self, '_holly_logged_mode', None) != self._holly_mode:
            log.info('HollyMovieHD monitoring mode: free public Jina reader (%s items)', len(items))
            self._holly_logged_mode = self._holly_mode
        return items
    except Exception as reader_error:
        self._holly_mode = 'unavailable'
        raise reader_error


async def enrich_with_reader_metadata(self, item):
    if item.source == 'HollyMovieHD' and getattr(self, '_holly_mode', '') == 'reader:jina':
        # Listing already contains poster, title, year and quality. Avoid the Holly
        # detail page because its Cloudflare policy rejects cloud-server IPs.
        return item
    return await _original_enrich(self, item)


async def bot_send_text_with_reader_status(text, chat_id=None):
    mode = getattr(getattr(core, 'service', None), 'scraper', None)
    mode = getattr(mode, '_holly_mode', 'unavailable')
    if mode == 'reader:jina':
        replacement = '✅ HollyMovieHD — active via free public metadata reader'
    elif mode == 'direct':
        replacement = '✅ HollyMovieHD — active (direct website)'
    else:
        replacement = '⚠️ HollyMovieHD — metadata source temporarily unavailable'

    for old in (
        '⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403',
        '⏸️ HollyMovieHD — cloud access is blocked (HTTP 403); skipped without stopping the bot',
        '⚠️ HollyMovieHD — website blocks cloud servers; public fallback currently unavailable',
    ):
        text = text.replace(old, replacement)
    return await _original_bot_send_text(text, chat_id)


core.Scraper.holly = holly_with_free_reader
core.Scraper.enrich = enrich_with_reader_metadata
core.bot_send_text = bot_send_text_with_reader_status
