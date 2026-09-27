import logging

import app as core

log = logging.getLogger("movie-bot")
CACHE_URL = "https://raw.githubusercontent.com/Vannarith-Git/feature/holly-cache/indonesia_horror_cache.json"

_original_collect = core.Service.collect
_original_bot_send_text = core.bot_send_text


async def _load_indonesia_items(service):
    response = await service.scraper.client.get(CACHE_URL)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("items") or []
    items = []
    for row in rows[:40]:
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if len(title) < 2 or not url.startswith("https://www.justwatch.com/id/movie/"):
            continue
        providers = str(row.get("provider") or "").strip()
        genres = str(row.get("category") or "Horror").strip()
        category = "Indonesian Horror"
        if genres:
            category += f" · {genres}"
        if providers:
            category += f" · {providers}"
        items.append(
            core.MovieItem(
                source="JustWatch Indonesia 🇮🇩",
                source_type="movie",
                title=title,
                url=url,
                poster_url=row.get("poster_url"),
                year=row.get("year"),
                quality=row.get("quality"),
                category=category,
            )
        )
    return items, payload


async def collect_with_indonesian_horror(self):
    items, errors = await _original_collect(self)
    try:
        indonesia_items, payload = await _load_indonesia_items(self)
        items.extend(indonesia_items)
        self.source_status = getattr(self, "source_status", {})
        self.source_status["Indonesian Horror"] = {
            "ok": True,
            "items": len(indonesia_items),
            "generated_at": payload.get("generated_at"),
        }

        # Seed the source once when it is first enabled so existing titles are
        # never blasted to Telegram as if they were newly released.
        if self.db.get_state("indonesia_source_initialized") != "1":
            for item in indonesia_items:
                self.db.add(item, False)
            self.db.set_state("indonesia_source_initialized", "1")
            log.info("Seeded Indonesian Horror baseline with %s titles", len(indonesia_items))
    except Exception as exc:
        errors.append(f"Indonesian Horror: {type(exc).__name__}: {exc}")
        log.warning("Indonesian Horror metadata unavailable: %s", type(exc).__name__)
    return items, errors


async def bot_send_text_with_indonesia_source(text, chat_id=None):
    if "🌐 <b>Monitoring Sources</b>" in text and "Indonesian Horror" not in text:
        text += "\n✅ 🇮🇩 Indonesian Horror — JustWatch Indonesia (Netflix, Prime Video, Catchplay, KlikFilm, Viu)"
    return await _original_bot_send_text(text, chat_id)


core.Service.collect = collect_with_indonesian_horror
core.bot_send_text = bot_send_text_with_indonesia_source
