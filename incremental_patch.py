import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import redis as redis_sync

import app as core

log = logging.getLogger("movie-bot")

REDIS_URL = os.getenv("REDIS_URL", "").strip()
SEEN_KEY = "moviebot:seen_urls:v1"
META_KEY = "moviebot:seen_meta:v1"
STATE_KEY = "moviebot:state:v1"
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "source"}

_original_has_url = core.DB.has_url
_original_add = core.DB.add
_original_get_state = core.DB.get_state
_original_set_state = core.DB.set_state

_rdb = redis_sync.Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
) if REDIS_URL else None


def canonical_url(url):
    raw = (url or "").strip()
    if not raw:
        return raw
    try:
        p = urlsplit(raw)
        scheme = (p.scheme or "https").lower()
        host = p.netloc.lower()
        path = p.path or "/"
        if path != "/":
            path = path.rstrip("/")
        query = []
        for key, value in parse_qsl(p.query, keep_blank_values=True):
            low = key.lower()
            if low.startswith("utm_") or low in TRACKING_PARAMS:
                continue
            query.append((key, value))
        return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))
    except Exception:
        return raw


def _meta_field(url):
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


def redis_available():
    if _rdb is None:
        return False
    return bool(_rdb.ping())


def persistent_has_url(self, url):
    if _rdb is None:
        return _original_has_url(self, canonical_url(url))
    return bool(_rdb.sismember(SEEN_KEY, canonical_url(url)))


def persistent_add(self, item, notified=False):
    if _rdb is None:
        return _original_add(self, item, notified)
    url = canonical_url(item.url)
    now = datetime.now(timezone.utc).isoformat()
    field = _meta_field(url)
    existing = _rdb.hget(META_KEY, field)
    first_seen = now
    old_notified = None
    if existing:
        try:
            data = json.loads(existing)
            first_seen = data.get("first_seen_at") or now
            old_notified = data.get("notified_at")
        except Exception:
            pass
    meta = {
        "source": item.source,
        "source_type": item.source_type,
        "url": url,
        "title": item.title,
        "year": item.year,
        "published_date": getattr(item, "published_date", None),
        "first_seen_at": first_seen,
        "notified_at": now if notified else old_notified,
    }
    pipe = _rdb.pipeline()
    pipe.sadd(SEEN_KEY, url)
    pipe.hset(META_KEY, field, json.dumps(meta, ensure_ascii=False))
    pipe.execute()


def persistent_get_state(self, key):
    if _rdb is None:
        return _original_get_state(self, key)
    return _rdb.hget(STATE_KEY, key)


def persistent_set_state(self, key, value):
    if _rdb is None:
        return _original_set_state(self, key, value)
    _rdb.hset(STATE_KEY, key, value)


def _source_state_key(source):
    return "source_initialized::" + source


def _published_sort_key(item):
    raw = str(getattr(item, "published_date", "") or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).timestamp()
        except Exception:
            pass
    try:
        return item.detected_at.astimezone(timezone.utc).timestamp()
    except Exception:
        return 0.0


STATUS_SOURCE_MAP = {
    "HollyMovieHD": "HollyMovieHD",
    "KhDiaMonD": "KhDiaMonD",
    "Indonesian Horror": "JustWatch Indonesia 🇮🇩",
    "anime": "Anime 🎌",
    "china_action": "Chinese Martial Arts 🥋",
}


async def run_once_incremental(self):
    """Send only items first observed after each source's baseline.

    Publication dates are metadata, not a today-only gate. Every successful
    poll compares the current source snapshot with persistent seen history.
    """
    if self.lock.locked():
        return {"status": "skipped", "reason": "run_in_progress"}

    async with self.lock:
        if _rdb is not None:
            try:
                redis_available()
            except Exception as exc:
                log.warning("Persistent alert state unavailable: %s", type(exc).__name__)
                return {"status": "state_unavailable", "sent": 0, "errors": ["persistent_state_unavailable"]}

        items, errors = await self.collect()
        groups = {}
        for item in items:
            groups.setdefault(item.source, []).append(item)

        baseline_sources = []
        candidates = []

        for source, source_items in groups.items():
            state_key = _source_state_key(source)
            if self.db.get_state(state_key) != "1":
                for item in source_items:
                    self.db.add(item, False)
                self.db.set_state(state_key, "1")
                baseline_sources.append(source)
                log.info("Seeded persistent baseline for %s with %s items", source, len(source_items))
                continue

            for item in source_items:
                if not self.db.has_url(item.url):
                    candidates.append(item)

        # A healthy source can legitimately be empty. Marking that empty
        # snapshot as initialized ensures its first future publication alerts.
        source_status = getattr(self, "source_status", {}) or {}
        for status_name, source_label in STATUS_SOURCE_MAP.items():
            status = source_status.get(status_name) or {}
            if status.get("ok") and source_label not in groups:
                key = _source_state_key(source_label)
                if self.db.get_state(key) != "1":
                    self.db.set_state(key, "1")
                    baseline_sources.append(source_label)

        if not core.TELEGRAM_BOT_TOKEN or not core.TELEGRAM_CHAT_ID:
            return {
                "status": "waiting_for_telegram",
                "fetched": len(items),
                "baseline_sources": baseline_sources,
                "pending_new": len(candidates),
                "sent": 0,
                "errors": errors,
            }

        tg = core.Telegram()
        sent = 0
        try:
            # Send oldest publication first so Telegram chronology reads naturally.
            for item in sorted(candidates, key=_published_sort_key):
                item = await self.scraper.enrich(item)
                await tg.send(item)
                self.db.add(item, True)
                sent += 1
        finally:
            await tg.close()

        return {
            "status": "ok",
            "fetched": len(items),
            "baseline_sources": baseline_sources,
            "new": len(candidates),
            "sent": sent,
            "state_backend": "redis" if _rdb is not None else "local",
            "errors": errors,
        }


core.DB.has_url = persistent_has_url
core.DB.add = persistent_add
core.DB.get_state = persistent_get_state
core.DB.set_state = persistent_set_state
core.Service.run_once = run_once_incremental
