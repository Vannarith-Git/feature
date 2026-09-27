import logging
import re
from urllib.parse import urlparse

import app as core

log = logging.getLogger('movie-bot')
READER_PREFIX = 'https://r.jina.ai/'
READER_LISTING = READER_PREFIX + 'https://hollymoviehd.cc/movies/'

_original_holly = core.Scraper.holly
_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text

SPECIAL_ROOT_SLUGS = {
    '', 'home', 'movies', 'series', 'recommended', 'most-viewed', 'request',
    'login', 'register', 'contact', 'dmca', 'privacy-policy', 'terms', 'about',
}
LINK_RE = re.compile(r'\[([^\]]*)\]\((https://hollymoviehd\.cc/[^\s)]+)(?:\s+"[^"]*")?\)', re.I)
IMAGE_RE = re.compile(r'!\[[^\]]*\]\((https?://[^\s)]+)(?:\s+"[^"]*")?\)', re.I)


def _is_movie_detail(url):
    parsed = urlparse(url)
    if parsed.netloc.lower() not in ('hollymoviehd.cc', 'www.hollymoviehd.cc'):
        return False
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) != 1:
        return False
    return parts[0].lower() not in SPECIAL_ROOT_SLUGS


def _clean_label(label, url):
    label = re.sub(r'^Image:\s*', '', label or '', flags=re.I).strip()
    label = label.replace('\\', '')
    title = core.clean_title(label)
    if len(title) >= 2 and title.lower() not in ('poster', 'image', 'watch now', 'details'):
        return title
    slug = urlparse(url).path.strip('/').replace('-', ' ')
    # Remove a trailing year from the slug only for the visible title.
    slug = re.sub(r'\s+(19\d{2}|20\d{2})$', '', slug)
    return core.clean_title(slug.title())


def _nearby_poster(markdown, start):
    window = markdown[max(0, start - 700):start]
    images = IMAGE_RE.findall(window)
    for image in reversed(images):
        low = image.lower()
        if 'logo' not in low and ('wp-content' in low or re.search(r'\.(?:jpe?g|png|webp)(?:\?|$)', low)):
            return image
    return None


def parse_reader_listing(markdown):
    out = []
    by_url = {}
    for match in LINK_RE.finditer(markdown):
        label, url = match.group(1), match.group(2)
        url = url.rstrip('.,;')
        if not _is_movie_detail(url):
            continue
        canonical = 'https://hollymoviehd.cc/' + urlparse(url).path.strip('/') + '/'
        title = _clean_label(label, canonical)
        if len(title) < 2:
            continue

        context = markdown[max(0, match.start() - 220):min(len(markdown), match.end() + 220)]
        year_match = core.YEAR_RE.search(label + ' ' + context)
        quality_match = core.QUALITY_RE.search(context)
        poster = _nearby_poster(markdown, match.start())
        item = core.MovieItem(
            'HollyMovieHD', 'movie', title, canonical, poster,
            year_match.group(1) if year_match else None,
            quality_match.group(1) if quality_match else None,
        )

        # The listing can contain the same detail URL more than once. Prefer the
        # occurrence with the most useful label/poster metadata while retaining
        # first-seen page order.
        existing = by_url.get(canonical)
        if existing:
            if len(item.title) > len(existing.title):
                existing.title = item.title
            existing.poster_url = existing.poster_url or item.poster_url
            existing.year = existing.year or item.year
            existing.quality = existing.quality or item.quality
            continue
        by_url[canonical] = item
        out.append(item)
        if len(out) >= core.MAX_ITEMS:
            break
    return out


def enrich_from_reader_text(item, markdown):
    genre = re.search(r'(?im)^\s*Genre:\s*(.+?)\s*$', markdown)
    quality = re.search(r'(?im)^\s*Quality:\s*(.+?)\s*$', markdown)
    release = re.search(r'(?im)^\s*Release:\s*((?:19|20)\d{2})\b', markdown)
    if genre:
        item.category = re.sub(r'\s{2,}', ' ', genre.group(1)).strip()
    if quality:
        value = quality.group(1).strip()
        q = core.QUALITY_RE.search(value)
        item.quality = q.group(1) if q else value[:30]
    if release:
        item.year = release.group(1)

    for image in IMAGE_RE.findall(markdown):
        low = image.lower()
        if 'logo' not in low and ('wp-content' in low or re.search(r'\.(?:jpe?g|png|webp)(?:\?|$)', low)):
            item.poster_url = image
            break
    return item


async def holly_with_reader(self):
    try:
        return await _original_holly(self)
    except Exception as original_error:
        try:
            response = await self.client.get(READER_LISTING, headers={'Accept': 'text/plain'})
            response.raise_for_status()
            items = parse_reader_listing(response.text)
            if not items:
                raise RuntimeError('public reader returned no movie detail links')
            self._holly_listing_url = READER_LISTING
            self._holly_mode = 'reader'
            if getattr(self, '_holly_logged_mode', None) != 'reader':
                log.info('HollyMovieHD monitoring via public metadata reader fallback (%s items)', len(items))
                self._holly_logged_mode = 'reader'
            return items
        except Exception as reader_error:
            self._holly_mode = 'unavailable'
            raise RuntimeError(
                f'Holly direct/public fallbacks unavailable; reader={type(reader_error).__name__}; '
                f'direct={type(original_error).__name__}'
            ) from reader_error


async def enrich_with_reader(self, item):
    if item.source == 'HollyMovieHD' and getattr(self, '_holly_mode', None) == 'reader':
        try:
            response = await self.client.get(READER_PREFIX + item.url, headers={'Accept': 'text/plain'})
            response.raise_for_status()
            return enrich_from_reader_text(item, response.text)
        except Exception as exc:
            log.warning('Holly reader detail enrichment unavailable: %s', type(exc).__name__)
            return item
    return await _original_enrich(self, item)


async def bot_send_text_with_reader_status(text, chat_id=None):
    old = '⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403'
    scraper = getattr(getattr(core, 'service', None), 'scraper', None)
    if old in text and getattr(scraper, '_holly_mode', None) == 'reader':
        text = text.replace(old, '✅ HollyMovieHD — active via public metadata reader fallback')
    return await _original_bot_send_text(text, chat_id)


core.Scraper.holly = holly_with_reader
core.Scraper.enrich = enrich_with_reader
core.bot_send_text = bot_send_text_with_reader_status
