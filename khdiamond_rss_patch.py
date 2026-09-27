import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import app as core

log = logging.getLogger("movie-bot")

FEEDS = [
    ("movie", "https://khdiamond.net/feed/?post_type=movies"),
    ("series", "https://khdiamond.net/feed/?post_type=tvshows"),
]


def _first_image(html_text):
    if not html_text:
        return None
    match = re.search(r'<img[^>]+src=["\']([^"\']+)', html_text, re.I)
    return match.group(1).strip() if match else None


async def khdiamond_from_rss(self):
    """Read only actual WordPress-published KhDiaMonD posts.

    Listing pages can reorder/import old catalogue titles. WordPress RSS exposes
    the post's authoritative pubDate, so every candidate carries a real site
    publication timestamp before the notification gate sees it.
    """
    out = []
    seen = set()
    for source_type, feed_url in FEEDS:
        response = await self.client.get(feed_url)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        for node in root.findall('./channel/item'):
            title = (node.findtext('title') or '').strip()
            url = (node.findtext('link') or '').strip()
            pub_raw = (node.findtext('pubDate') or '').strip()
            if not title or not url or not pub_raw or url in seen:
                continue
            try:
                published = parsedate_to_datetime(pub_raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=core.timezone.utc)
                published_iso = published.isoformat()
            except Exception:
                continue

            description = node.findtext('description') or ''
            content_encoded = ''
            for child in list(node):
                if child.tag.endswith('encoded'):
                    content_encoded = child.text or ''
                    break
            poster = _first_image(content_encoded) or _first_image(description)

            out.append(core.MovieItem(
                source='KhDiaMonD',
                source_type=source_type,
                title=title,
                url=url,
                poster_url=poster,
                category='Series' if source_type == 'series' else 'Movie',
                published_date=published_iso,
            ))
            seen.add(url)
            if len(out) >= core.MAX_ITEMS * 2:
                return out
    return out


core.Scraper.khdiamond = khdiamond_from_rss
