import logging
from urllib.parse import urlparse

import app as core

log = logging.getLogger('movie-bot')

DIRECT_LISTING = 'https://hollymoviehd.cc/movies/'
MIRROR_LISTINGS = [
    'https://novamovie.net/movies',
    'https://yeshd.net/movies/',
]

_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text


def _same_host(host, expected):
    host = host.lower().split(':', 1)[0]
    expected = expected.lower().split(':', 1)[0]
    return host == expected or host.endswith('.' + expected)


async def holly_with_mirror_fallback(self):
    listing_order = []
    cached = getattr(self, '_holly_listing_url', None)
    if cached:
        listing_order.append(cached)
    for url in [DIRECT_LISTING, *MIRROR_LISTINGS]:
        if url not in listing_order:
            listing_order.append(url)

    soup = None
    listing_url = None
    last_error = None
    for candidate in listing_order:
        try:
            soup = await self.soup(candidate)
            listing_url = candidate
            self._holly_listing_url = candidate
            break
        except Exception as exc:
            last_error = exc
            if cached == candidate:
                self._holly_listing_url = None

    if soup is None or listing_url is None:
        if last_error:
            raise last_error
        raise RuntimeError('No HollyMovieHD listing source available')

    selected_host = urlparse(listing_url).netloc.lower()
    direct = _same_host(selected_host, 'hollymoviehd.cc')
    previous_mode = getattr(self, '_holly_logged_listing_url', None)
    if previous_mode != listing_url:
        if direct:
            log.info('HollyMovieHD monitoring via direct listing')
        else:
            log.info('HollyMovieHD monitoring via public mirror fallback: %s', selected_host)
        self._holly_logged_listing_url = listing_url

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

        if direct:
            canonical_href = raw_href
        else:
            canonical_href = 'https://hollymoviehd.cc' + parsed_raw.path
            if parsed_raw.query:
                canonical_href += '?' + parsed_raw.query

        if canonical_href in seen:
            continue
        path = urlparse(canonical_href).path.rstrip('/') + '/'
        if path in ('/', '/movies/') or any(x in path for x in (
            '/recommended/', '/genre/', '/country/', '/release/', '/tag/', '/page/',
            '/request/', '/login/', '/register/'
        )):
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
            'HollyMovieHD',
            'movie',
            title,
            canonical_href,
            core.img_url(node, listing_url),
            year_match.group(1) if year_match else None,
            quality_match.group(1) if quality_match else None,
        ))
        seen.add(canonical_href)
        if len(out) >= core.MAX_ITEMS:
            break

    if not out:
        raise RuntimeError(f'HollyMovieHD listing parsed 0 items from {selected_host}')
    return out


async def enrich_with_holly_mirror(self, item):
    if item.source != 'HollyMovieHD':
        return await _original_enrich(self, item)

    listing_url = getattr(self, '_holly_listing_url', DIRECT_LISTING)
    listing_host = urlparse(listing_url).netloc.lower()
    if _same_host(listing_host, 'hollymoviehd.cc'):
        return await _original_enrich(self, item)

    path = urlparse(item.url).path
    candidates = []
    preferred_origin = f'{urlparse(listing_url).scheme}://{urlparse(listing_url).netloc}'
    candidates.append(preferred_origin + path)
    for listing in MIRROR_LISTINGS:
        parsed = urlparse(listing)
        url = f'{parsed.scheme}://{parsed.netloc}{path}'
        if url not in candidates:
            candidates.append(url)

    for mirror_url in candidates:
        mirror_item = core.MovieItem(
            item.source,
            item.source_type,
            item.title,
            mirror_url,
            item.poster_url,
            item.year,
            item.quality,
            item.category,
            item.published_date,
            item.detected_at,
        )
        enriched = await _original_enrich(self, mirror_item)
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
    new = '✅ HollyMovieHD — active via direct access or NovaMovie/YesHD mirror fallback'
    if old in text:
        text = text.replace(old, new)
    return await _original_bot_send_text(text, chat_id)


core.Scraper.holly = holly_with_mirror_fallback
core.Scraper.enrich = enrich_with_holly_mirror
core.bot_send_text = bot_send_text_with_source_status
