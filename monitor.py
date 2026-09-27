import asyncio
import json
import os
from pathlib import Path

from app import Scraper, Telegram

STATE_PATH = Path(os.getenv('STATE_PATH', 'state.json'))


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {'initialized': False, 'seen': []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError
        data.setdefault('initialized', False)
        data.setdefault('seen', [])
        return data
    except Exception:
        return {'initialized': False, 'seen': []}


def save_state(state: dict) -> None:
    seen = list(dict.fromkeys(state.get('seen', [])))
    state['seen'] = seen[-2000:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


async def main() -> int:
    scraper = Scraper()
    try:
        items = []
        errors = []
        for source, fn in [('HollyMovieHD', scraper.holly), ('KhDiaMonD', scraper.khdiamond)]:
            try:
                items.extend(await fn())
            except Exception as exc:
                errors.append(f'{source}: {type(exc).__name__}: {exc}')

        if not items:
            print(json.dumps({'status': 'source_unavailable', 'errors': errors}, ensure_ascii=False))
            return 2

        state = load_state()
        seen = set(state.get('seen', []))

        if not state.get('initialized'):
            seen.update(item.url for item in items)
            state = {'initialized': True, 'seen': sorted(seen)}
            save_state(state)
            print(json.dumps({'status': 'seeded', 'fetched': len(items), 'errors': errors}, ensure_ascii=False))
            return 0

        new_items = [item for item in items if item.url not in seen]
        if not new_items:
            print(json.dumps({'status': 'ok', 'fetched': len(items), 'new': 0, 'sent': 0, 'errors': errors}, ensure_ascii=False))
            return 0

        token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()
        if not token or not chat_id:
            print(json.dumps({'status': 'waiting_for_telegram', 'new': len(new_items), 'errors': errors}, ensure_ascii=False))
            return 3

        tg = Telegram()
        sent = 0
        try:
            for item in reversed(new_items):
                item = await scraper.enrich(item)
                await tg.send(item)
                seen.add(item.url)
                sent += 1
                state = {'initialized': True, 'seen': sorted(seen)}
                save_state(state)
        finally:
            await tg.close()

        print(json.dumps({'status': 'ok', 'fetched': len(items), 'new': len(new_items), 'sent': sent, 'errors': errors}, ensure_ascii=False))
        return 0
    finally:
        await scraper.close()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
