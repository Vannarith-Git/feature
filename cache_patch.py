import logging
from datetime import datetime, timezone

import app as core

log = logging.getLogger("movie-bot")

CACHE_URL = "https://raw.githubusercontent.com/Vannarith-Git/feature/holly-cache/holly_cache.json"

_original_holly = core.Scraper.holly
_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text


def _valid_holly_url(url):
    return isinstance(url, str) and url.startswith("https://hollymoviehd.cc/") and url.count("/") >= 3


async def holly_with_free_cache(self):
    try:
        direct = await _original_holly(self)
        if direct:
            self._holly_mode = "direct"
            return direct
    except Exception as exc:
        self._holly_direct_error = type(exc).__name__

    response = await self.client.get(CACHE_URL)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("items") or []
    items = []

    for row in rows[: core.MAX_ITEMS]:
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if len(title) < 2 or not _valid_holly_url(url):
            continue
        items.append(
            core.MovieItem(
                source="HollyMovieHD",
                source_type=str(row.get("source_type") or "movie"),
                title=title,
                url=url,
                poster_url=row.get("poster_url"),
                year=row.get("year"),
                quality=row.get("quality"),
            )
        )

    if not items:
        raise RuntimeError("HollyMovieHD metadata cache is empty")

    self._holly_mode = "github-cache"
    self._holly_cache_generated_at = payload.get("generated_at")
    self._holly_metadata_source = payload.get("metadata_source") or "mirror"

    # Seed the current Holly listing exactly once so enabling the fallback does
    # not send a flood of old titles. Only titles added after this baseline will
    # be notified.
    service = getattr(core, "service", None)
    if service is not None:
        try:
            if service.db.get_state("holly_source_initialized") != "1":
                for item in items:
                    service.db.add(item, False)
                service.db.set_state("holly_source_initialized", "1")
                log.info("Seeded HollyMovieHD cache baseline with %s items", len(items))
        except Exception as exc:
            log.warning("Could not seed HollyMovieHD baseline: %s", type(exc).__name__)

    if getattr(self, "_holly_logged_mode", None) != "github-cache":
        log.info(
            "HollyMovieHD active via free GitHub metadata cache (%s items, source=%s, generated_at=%s)",
            len(items),
            self._holly_metadata_source,
            self._holly_cache_generated_at,
        )
        self._holly_logged_mode = "github-cache"
    return items


async def enrich_without_blocked_detail(self, item):
    if item.source == "HollyMovieHD" and getattr(self, "_holly_mode", "") == "github-cache":
        return item
    return await _original_enrich(self, item)


async def bot_send_text_with_cache_status(text, chat_id=None):
    scraper = getattr(getattr(core, "service", None), "scraper", None)
    mode = getattr(scraper, "_holly_mode", "unavailable")
    metadata_source = getattr(scraper, "_holly_metadata_source", "mirror")

    if mode == "github-cache":
        replacement = f"✅ HollyMovieHD — active via free metadata cache ({metadata_source})"
    elif mode == "direct":
        replacement = "✅ HollyMovieHD — active (direct website)"
    else:
        replacement = "⚠️ HollyMovieHD — metadata source temporarily unavailable"

    for old in (
        "⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403",
        "⏸️ HollyMovieHD — cloud access is blocked (HTTP 403); skipped without stopping the bot",
        "⚠️ HollyMovieHD — website blocks cloud servers; public fallback currently unavailable",
        "⚠️ HollyMovieHD — metadata source temporarily unavailable",
    ):
        text = text.replace(old, replacement)
    return await _original_bot_send_text(text, chat_id)


core.Scraper.holly = holly_with_free_cache
core.Scraper.enrich = enrich_without_blocked_detail
core.bot_send_text = bot_send_text_with_cache_status
