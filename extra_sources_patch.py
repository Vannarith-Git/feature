import logging

import app as core

log = logging.getLogger("movie-bot")

SOURCES = [
    {
        "key": "anime",
        "label": "Anime 🎌",
        "cache_url": "https://raw.githubusercontent.com/Vannarith-Git/feature/holly-cache/anime_cache.json",
        "state_key": "anime_source_initialized",
        "default_category": "Anime",
    },
    {
        "key": "china_action",
        "label": "Chinese Action 🥋",
        "cache_url": "https://raw.githubusercontent.com/Vannarith-Git/feature/holly-cache/china_action_cache.json",
        "state_key": "china_action_source_initialized",
        "default_category": "Chinese Action / Martial Arts",
    },
]

_original_collect = core.Service.collect
_original_enrich = core.Scraper.enrich
_original_bot_send_text = core.bot_send_text


async def _load_items(service, spec):
    response = await service.scraper.client.get(spec["cache_url"])
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("items") or []
    items = []
    for row in rows[:60]:
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if len(title) < 2 or not url.startswith("https://www.justwatch.com/id/"):
            continue
        category = str(row.get("category") or spec["default_category"]).strip()
        provider = str(row.get("provider") or "").strip()
        country = str(row.get("country") or "").strip()
        if provider:
            category += f" · {provider}"
        if country and country not in category:
            category += f" · {country}"
        items.append(
            core.MovieItem(
                source=spec["label"],
                source_type=str(row.get("source_type") or "movie"),
                title=title,
                url=url,
                poster_url=row.get("poster_url"),
                year=row.get("year"),
                quality=row.get("quality"),
                category=category,
            )
        )
    return items, payload


async def collect_with_extra_sources(self):
    items, errors = await _original_collect(self)
    for spec in SOURCES:
        try:
            extra_items, payload = await _load_items(self, spec)
            items.extend(extra_items)
            self.source_status = getattr(self, "source_status", {})
            self.source_status[spec["key"]] = {
                "ok": True,
                "items": len(extra_items),
                "generated_at": payload.get("generated_at"),
            }

            # First activation is a silent baseline so old catalogue items are
            # never sent as if they were newly released.
            if self.db.get_state(spec["state_key"]) != "1":
                for item in extra_items:
                    self.db.add(item, False)
                self.db.set_state(spec["state_key"], "1")
                log.info("Seeded %s baseline with %s titles", spec["label"], len(extra_items))
        except Exception as exc:
            # Cache might not exist for a few minutes during first deployment.
            # Keep the rest of the bot working and try again next run.
            errors.append(f"{spec['label']}: {type(exc).__name__}: {exc}")
            log.warning("%s metadata unavailable: %s", spec["label"], type(exc).__name__)
    return items, errors


async def enrich_cached_extra_source(self, item):
    if item.source in {spec["label"] for spec in SOURCES}:
        return item
    return await _original_enrich(self, item)


async def bot_send_text_with_extra_sources(text, chat_id=None):
    if "🌐 <b>Monitoring Sources</b>" in text:
        if "Anime 🎌" not in text:
            text += "\n✅ 🎌 Anime — Crunchyroll + Netflix via JustWatch Indonesia"
        if "Chinese Action" not in text:
            text += "\n✅ 🥋 Chinese Action / Martial Arts — China/Hong Kong action movies via JustWatch Indonesia"
    return await _original_bot_send_text(text, chat_id)


core.Service.collect = collect_with_extra_sources
core.Scraper.enrich = enrich_cached_extra_source
core.bot_send_text = bot_send_text_with_extra_sources
