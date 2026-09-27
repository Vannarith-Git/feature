import logging
import re
from urllib.parse import urlparse

import app as core

log = logging.getLogger('movie-bot')

DIRECT_LISTING = 'https://hollymoviehd.cc/movies/'
MIRROR_LISTINGS = [
    'https://novamovie.net/movies',
    'https://yeshd.net/movies/',
]
TELEGRAM_PREVIEW = 'https://t.me/s/hollymoviehd'
RELATED_HOSTS = ('hollymoviehd.cc', 'novamovie.net', 'yeshd.net')

_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text


def _same_host(host, expected):
    host = host.lower().split(':', 1)[0]
    expected = expected.lower().split(':', 1)[0]
    return host == expected or host.endswith('.' + expected)


def _canonical_holly_url(raw_url):
    parsed = urlparse(raw_url)
    if not any(_same_host(parsed.netloc, host) for host in RELATED_HOSTS):
        return None
    path = parsed.path.rstrip('/') + '/'
    if path in ('/', '/movies/') or any(x in path for x in (
        '/recommended/', '/genre/', '/country/', '/release/', '/release-year/',
        '/tag/', '/page/', '/request/', '/login/', '/register/', '/most-viewed/'
    )):
        return None
    url = 'https://hollymoviehd.cc' + parsed.path
    if parsed.query:
        url += '?' + parsed.query
    return url


def _photo_from_telegram(message):
    photo = message.select_one('.tgme_widget_message_photo_wrap')
    if photo:
        style = str(photo.get('style') or '')
        match = re.search(r"background-image\s*:\s*url\(['\"]?([^)'\"]+)", style, re.I)
        if match:
            return match.group(1)
    image = message.find('img')
    if image:
        src = image.get('src') or image.get('data-src')
        if src and not str(src).startswith('data:'):
            return str(src)
    return None


def _telegram_title(message, target_anchor, text):
    anchor_text = core.clean_title(core.node_text(target_anchor)) if target_anchor else ''
    if anchor_text and len(anchor_text) >= 2 and not anchor_text.lower().startswith(('http://', 'https://')):
        return anchor_text

    text_node = message.select_one('.tgme_widget_message_text')
    raw = text_node.get_text('\n', strip=True) if text_node else text
    for line in raw.splitlines():
        line = line.strip().lstrip('🎬🎥🍿📺▶️•- ').strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(('http://', 'https://', 'watch ', 'download ', 'source:', 'quality:', 'genre:')):
            continue
        cleaned = core.clean_title(line)
        if len(cleaned) >= 2:
            return cleaned
    return ''


def _parse_standard_listing(soup, listing_url):
    selected_host = urlparse(listing_url).netloc.lower()
    direct = _same_host(selected_host, 'hollymoviehd.cc')
    candidates = soup.select('article,.item,.items .item,.movies .item,.result-item,.ml-item,.poster,.movie-item')
    if not candidates:
        candidates = [a.parent for a in soup.find_all('a', href=True) if a.find('img') and a.parent]

    out, seen = [], set()
    for node in candidates:
        if not isinstance(node, core.Tag):
            continue
        anchors = node.find_all('a', href=True)
        anchor = next((x for x in anchors if x.find('img')), anchors[0] if anchors else None)
        if not anchor:
            continue

        raw_href = core.abs_url(listing_url, anchor.get('href'))
        if not raw_href:
            continue
        parsed_raw = urlparse(raw_href)
        if not _same_host(parsed_raw.netloc, selected_host):
            continue
        canonical_href = raw_href if direct else _canonical_holly_url(raw_href)
        if not canonical_href or canonical_href in seen:
            continue

        title = ''
        for selector in ('h1', 'h2', 'h3', '.title', '.data h3', '.name'):
            title_node = node.select_one(selector)
            if title_node and core.node_text(title_node):
                title = core.clean_title(core.node_text(title_node))
                break
        if not title:
            image = anchor.find('img') or node.find('img')
            title = core.clean_title(str(
                (image.get('alt') or image.get('title') or '') if image else core.node_text(anchor)
            ))
        if len(title) < 2:
            continue

        text = core.node_text(node)
        year_match = core.YEAR_RE.search(text or title)
        quality_match = core.QUALITY_RE.search(text)
        out.append(core.MovieItem(
            'HollyMovieHD', 'movie', title, canonical_href,
            core.img_url(node, listing_url),
            year_match.group(1) if year_match else None,
            quality_match.group(1) if quality_match else None,
        ))
        seen.add(canonical_href)
        if len(out) >= core.MAX_ITEMS:
            break
    return out


def _parse_telegram_preview(soup):
    messages = soup.select('.tgme_widget_message_wrap, .tgme_widget_message')
    out, seen = [], set()
    for message in reversed(messages):
        if not isinstance(message, core.Tag):
            continue
        text = core.node_text(message)
        target_anchor = None
        canonical_href = None
        for anchor in message.find_all('a', href=True):
            raw_href = str(anchor.get('href') or '').strip()
            candidate = _canonical_holly_url(raw_href)
            if candidate:
                target_anchor = anchor
                canonical_href = candidate
                break
        if not canonical_href or canonical_href in seen:
            continue

        title = _telegram_title(message, target_anchor, text)
        if len(title) < 2:
            slug = urlparse(canonical_href).path.strip('/').replace('-', ' ')
            title = core.clean_title(slug.title())
        if len(title) < 2:
            continue

        year_match = core.YEAR_RE.search(text or title)
        quality_match = core.QUALITY_RE.search(text)
        out.append(core.MovieItem(
            'HollyMovieHD', 'movie', title, canonical_href,
            _photo_from_telegram(message),
            year_match.group(1) if year_match else None,
            quality_match.group(1) if quality_match else None,
        ))
        seen.add(canonical_href)
        if len(out) >= core.MAX_ITEMS:
            break
    return out


async def holly_with_public_fallbacks(self):
    listing_order = []
    cached = getattr(self, '_holly_listing_url', None)
    if cached and cached != TELEGRAM_PREVIEW:
        listing_order.append(cached)
    for url in [DIRECT_LISTING, *MIRROR_LISTINGS]:
        if url not in listing_order:
            listing_order.append(url)

    last_error = None
    for listing_url in listing_order:
        try:
            soup = await self.soup(listing_url)
            out = _parse_standard_listing(soup, listing_url)
            if not out:
                raise RuntimeError(f'parsed 0 items from {urlparse(listing_url).netloc}')
            self._holly_listing_url = listing_url
            host = urlparse(listing_url).netloc.lower()
            self._holly_mode = 'direct' if _same_host(host, 'hollymoviehd.cc') else f'mirror:{host}'
            if getattr(self, '_holly_logged_mode', None) != self._holly_mode:
                log.info('HollyMovieHD monitoring mode: %s', self._holly_mode)
                self._holly_logged_mode = self._holly_mode
            return out
        except Exception as exc:
            last_error = exc

    # Official HollyMovieHD Telegram public preview is the final metadata fallback.
    # This does not use Telegram credentials and reads only publicly visible posts.
    try:
        soup = await self.soup(TELEGRAM_PREVIEW)
        out = _parse_telegram_preview(soup)
        if not out:
            raise RuntimeError('official Telegram preview contains no Holly detail links')
        self._holly_listing_url = TELEGRAM_PREVIEW
        self._holly_mode = 'telegram'
        if getattr(self, '_holly_logged_mode', None) != self._holly_mode:
            log.info('HollyMovieHD monitoring via official public Telegram channel fallback')
            self._holly_logged_mode = self._holly_mode
        return out
    except Exception as exc:
        last_error = exc

    self._holly_mode = 'unavailable'
    if last_error:
        raise last_error
    raise RuntimeError('No HollyMovieHD public metadata source available')


async def enrich_with_holly_fallback(self, item):
    if item.source != 'HollyMovieHD':
        return await _original_enrich(self, item)

    listing_url = getattr(self, '_holly_listing_url', DIRECT_LISTING)
    listing_host = urlparse(listing_url).netloc.lower()
    if _same_host(listing_host, 'hollymoviehd.cc'):
        return await _original_enrich(self, item)

    # When direct Holly detail pages are blocked, enrich from public mirror detail
    # pages where available. Telegram metadata already present on the item remains
    # as a fallback if mirror detail pages are also blocked.
    path = urlparse(item.url).path
    candidates = []
    if listing_url != TELEGRAM_PREVIEW:
        parsed_listing = urlparse(listing_url)
        candidates.append(f'{parsed_listing.scheme}://{parsed_listing.netloc}{path}')
    for listing in MIRROR_LISTINGS:
        parsed = urlparse(listing)
        url = f'{parsed.scheme}://{parsed.netloc}{path}'
        if url not in candidates:
            candidates.append(url)

    for mirror_url in candidates:
        mirror_item = core.MovieItem(
            item.source, item.source_type, item.title, mirror_url,
            item.poster_url, item.year, item.quality, item.category,
            item.published_date, item.detected_at,
        )
        try:
            enriched = await _original_enrich(self, mirror_item)
        except Exception:
            continue
        if enriched.category or enriched.published_date or enriched.poster_url or enriched.quality or enriched.year:
            item.poster_url = enriched.poster_url or item.poster_url
            item.year = enriched.year or item.year
            item.quality = enriched.quality or item.quality
            item.category = enriched.category or item.category
            item.published_date = enriched.published_date or item.published_date
            return item
    return item


async def bot_send_text_with_source_status(text, chat_id=None):
    old = '⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403'
    if old in text:
        mode = getattr(getattr(core, 'service', None), 'scraper', None)
        mode = getattr(mode, '_holly_mode', 'unavailable')
        if mode == 'direct':
            replacement = '✅ HollyMovieHD — active (direct website)'
        elif str(mode).startswith('mirror:'):
            replacement = '✅ HollyMovieHD — active via public mirror metadata fallback'
        elif mode == 'telegram':
            replacement = '✅ HollyMovieHD — active via official @hollymoviehd public channel fallback'
        else:
            replacement = '⚠️ HollyMovieHD — website blocks cloud servers; public fallback currently unavailable'
        text = text.replace(old, replacement)
    return await _original_bot_send_text(text, chat_id)


core.Scraper.holly = holly_with_public_fallbacks
core.Scraper.enrich = enrich_with_holly_fallback
core.bot_send_text = bot_send_text_with_source_status
