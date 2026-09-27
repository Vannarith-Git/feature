import logging
import time

import httpx
import app as core

log = logging.getLogger("movie-bot")

_original_bot_send_text = core.bot_send_text
HOLLY_RETRY_SECONDS = 60 * 60
_holly_blocked_until = 0.0


async def collect_without_holly_403_errors(self):
    """Keep the bot healthy and cheap when Holly rejects cloud-hosted requests."""
    global _holly_blocked_until

    items, errors = [], []
    self.source_status = {}

    sources = []
    now = time.monotonic()
    if now >= _holly_blocked_until:
        sources.append(("HollyMovieHD", self.scraper.holly))
    else:
        self.source_status["HollyMovieHD"] = {
            "ok": False,
            "state": "cloud_blocked_backoff",
            "retry_in_seconds": max(0, int(_holly_blocked_until - now)),
        }

    sources.append(("KhDiaMonD", self.scraper.khdiamond))

    for name, fn in sources:
        try:
            fetched = await fn()
            items.extend(fetched)
            self.source_status[name] = {"ok": True, "items": len(fetched)}
            if name == "HollyMovieHD":
                _holly_blocked_until = 0.0
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if name == "HollyMovieHD" and status == 403:
                _holly_blocked_until = time.monotonic() + HOLLY_RETRY_SECONDS
                self.source_status[name] = {
                    "ok": False,
                    "state": "cloud_blocked",
                    "http_status": 403,
                    "retry_after_seconds": HOLLY_RETRY_SECONDS,
                }
                log.info("HollyMovieHD cloud access blocked (403); retrying in 1 hour")
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
        "⏸️ HollyMovieHD — cloud access blocked (HTTP 403); bot retries automatically every hour",
    )
    return await _original_bot_send_text(text, chat_id)


core.Service.collect = collect_without_holly_403_errors
core.bot_send_text = bot_send_text_free_mode
