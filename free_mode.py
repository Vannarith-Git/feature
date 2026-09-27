import logging

import httpx
import app as core

log = logging.getLogger("movie-bot")

_original_bot_send_text = core.bot_send_text


async def collect_without_holly_403_errors(self):
    """Keep the bot healthy when HollyMovieHD rejects cloud-hosted requests.

    HTTP 403 from HollyMovieHD is an upstream access policy, not an application
    failure. The source is skipped for that run while every other configured
    source continues normally. Real scraper/network errors still surface.
    """
    items, errors = [], []
    self.source_status = {}

    for name, fn in [
        ("HollyMovieHD", self.scraper.holly),
        ("KhDiaMonD", self.scraper.khdiamond),
    ]:
        try:
            fetched = await fn()
            items.extend(fetched)
            self.source_status[name] = {"ok": True, "items": len(fetched)}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if name == "HollyMovieHD" and status == 403:
                self.source_status[name] = {
                    "ok": False,
                    "state": "cloud_blocked",
                    "http_status": 403,
                }
                log.info("HollyMovieHD skipped: site rejects this cloud IP with HTTP 403")
                continue
            errors.append(f"{name}: HTTPStatusError: HTTP {status or 'unknown'}")
            self.source_status[name] = {"ok": False, "state": "error"}
            log.warning("%s unavailable: HTTP %s", name, status or "unknown")
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            self.source_status[name] = {"ok": False, "state": "error"}
            log.warning("%s unavailable: %s", name, type(exc).__name__)

    return items, errors


async def bot_send_text_free_mode(text, chat_id=None):
    text = text.replace(
        "⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403",
        "⏸️ HollyMovieHD — cloud access is blocked (HTTP 403); skipped without stopping the bot",
    )
    return await _original_bot_send_text(text, chat_id)


core.Service.collect = collect_without_holly_403_errors
core.bot_send_text = bot_send_text_free_mode
