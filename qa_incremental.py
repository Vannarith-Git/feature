#!/usr/bin/env python3
import asyncio
from datetime import datetime, timezone

import app as core
import incremental_patch as inc


class FakeDB:
    def __init__(self):
        self.seen = set()
        self.state = {}

    def has_url(self, url):
        return inc.canonical_url(url) in self.seen

    def add(self, item, notified=False):
        self.seen.add(inc.canonical_url(item.url))

    def get_state(self, key):
        return self.state.get(key)

    def set_state(self, key, value):
        self.state[key] = value


class FakeScraper:
    async def enrich(self, item):
        return item


class FakeTelegram:
    sent = []

    def __init__(self):
        pass

    async def send(self, item):
        self.__class__.sent.append(item.url)

    async def close(self):
        pass


class FakeService:
    def __init__(self, db, items):
        self.db = db
        self.items = items
        self.scraper = FakeScraper()
        self.lock = asyncio.Lock()
        self.source_status = {}

    async def collect(self):
        return list(self.items), []


def movie(source, title, url, published):
    return core.MovieItem(
        source=source,
        source_type="movie",
        title=title,
        url=url,
        published_date=published,
        detected_at=datetime.now(timezone.utc),
    )


async def unit_qa():
    core.TELEGRAM_BOT_TOKEN = "qa-token-not-real"
    core.TELEGRAM_CHAT_ID = "qa-chat"
    original_tg = core.Telegram
    core.Telegram = FakeTelegram
    FakeTelegram.sent = []

    try:
        db = FakeDB()
        old_a = movie("KhDiaMonD", "Old A", "https://khdiamond.net/movies/a/", "2026-09-01T10:00:00+07:00")
        old_b = movie("KhDiaMonD", "Old B", "https://khdiamond.net/movies/b/", "2026-09-02T10:00:00+07:00")
        svc = FakeService(db, [old_a, old_b])

        first = await inc.run_once_incremental(svc)
        assert first["sent"] == 0
        assert "KhDiaMonD" in first["baseline_sources"]
        assert len(db.seen) == 2

        second = await inc.run_once_incremental(svc)
        assert second["new"] == 0 and second["sent"] == 0

        # The publication date can be yesterday/older. If the URL truly appears
        # after the previous snapshot, it must alert; date is metadata, not a gate.
        newly_observed = movie("KhDiaMonD", "Newly observed", "https://khdiamond.net/movies/c/", "2026-09-03T10:00:00+07:00")
        svc.items = [newly_observed, old_a, old_b]
        third = await inc.run_once_incremental(svc)
        assert third["new"] == 1 and third["sent"] == 1
        assert FakeTelegram.sent == ["https://khdiamond.net/movies/c/"]

        fourth = await inc.run_once_incremental(svc)
        assert fourth["new"] == 0 and fourth["sent"] == 0

        # Restart with the same persistent state: no duplicate alert.
        restarted = FakeService(db, list(svc.items))
        after_restart = await inc.run_once_incremental(restarted)
        assert after_restart["new"] == 0 and after_restart["sent"] == 0

        # URL normalization prevents tracking/trailing-slash duplicates.
        restarted.items = [
            movie("KhDiaMonD", "Same C", "https://khdiamond.net/movies/c?utm_source=test", "2026-09-03T10:00:00+07:00"),
            old_a,
            old_b,
        ]
        canonical = await inc.run_once_incremental(restarted)
        assert canonical["new"] == 0 and canonical["sent"] == 0

        # A newly enabled source gets one silent baseline, then future items alert.
        source_first = movie("Test Source", "Baseline", "https://example.com/1", None)
        restarted.items = list(svc.items) + [source_first]
        source_baseline = await inc.run_once_incremental(restarted)
        assert source_baseline["sent"] == 0
        assert "Test Source" in source_baseline["baseline_sources"]

        source_new = movie("Test Source", "Future", "https://example.com/2", None)
        restarted.items = list(svc.items) + [source_new, source_first]
        source_next = await inc.run_once_incremental(restarted)
        assert source_next["new"] == 1 and source_next["sent"] == 1

        print("PASS unit: baseline is silent")
        print("PASS unit: newly observed URL sends regardless of publication calendar date")
        print("PASS unit: duplicate and restart do not resend")
        print("PASS unit: new source baseline prevents catalogue blast")
    finally:
        core.Telegram = original_tg


async def live_khdiamond_qa():
    scraper = core.Scraper()
    try:
        items = await scraper.khdiamond()
    finally:
        await scraper.close()

    assert items, "KhDiaMonD RSS returned no items"
    assert all(item.published_date for item in items), "RSS item missing pubDate"

    core.TELEGRAM_BOT_TOKEN = "qa-token-not-real"
    core.TELEGRAM_CHAT_ID = "qa-chat"
    original_tg = core.Telegram
    core.Telegram = FakeTelegram
    FakeTelegram.sent = []
    try:
        db = FakeDB()
        svc = FakeService(db, items)
        first = await inc.run_once_incremental(svc)
        second = await inc.run_once_incremental(svc)
        assert first["sent"] == 0
        assert second["new"] == 0 and second["sent"] == 0

        # Simulate a new RSS publication while keeping an older pubDate. The bot
        # must alert because it is a new post since the previous check.
        synthetic = movie(
            "KhDiaMonD",
            "QA synthetic publication",
            "https://khdiamond.net/movies/qa-new-post/",
            "2026-09-20T10:00:00+07:00",
        )
        svc.items = [synthetic] + items
        third = await inc.run_once_incremental(svc)
        assert third["new"] == 1 and third["sent"] == 1

        print(f"PASS live KhDiaMonD RSS: baseline={len(items)}, duplicate=0, synthetic_new=1")
        print("PASS dry-run: no real Telegram credentials were used")
    finally:
        core.Telegram = original_tg


async def main():
    await unit_qa()
    await live_khdiamond_qa()


if __name__ == "__main__":
    asyncio.run(main())
