import asyncio
import html
import logging
import os
import re
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
import psycopg
from bs4 import BeautifulSoup, Tag
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('movie-bot')

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '').strip()
DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
TIMEZONE = os.getenv('TIMEZONE', 'Asia/Phnom_Penh')
SEED_ON_FIRST_RUN = os.getenv('SEED_ON_FIRST_RUN', 'true').lower() == 'true'
MAX_ITEMS = int(os.getenv('MAX_ITEMS_PER_SOURCE', '30'))
TIMEOUT = float(os.getenv('HTTP_TIMEOUT_SECONDS', '20'))
USER_AGENT = os.getenv('USER_AGENT', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
YEAR_RE = re.compile(r'\b(19\d{2}|20\d{2})\b')
QUALITY_RE = re.compile(r'\b(4K|UHD|BluRay|WEB[- .]?DL|WEBRip|HDTS|HDTC|HDRip|HD|CAM|TS)\b', re.I)

@dataclass(slots=True)
class MovieItem:
    source: str
    source_type: str
    title: str
    url: str
    poster_url: str | None = None
    year: str | None = None
    quality: str | None = None
    category: str | None = None
    published_date: str | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

class DB:
    def __init__(self):
        self.pg = DATABASE_URL.startswith(('postgres://', 'postgresql://'))
        self.sqlite_path = '/tmp/movie_alerts.db'
        self.init()

    @contextmanager
    def conn(self):
        conn = psycopg.connect(DATABASE_URL) if self.pg else sqlite3.connect(self.sqlite_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self):
        schema = '''CREATE TABLE IF NOT EXISTS seen_items (
            id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, source_type TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, year TEXT,
            first_seen_at TEXT NOT NULL, notified_at TEXT)''' if self.pg else '''CREATE TABLE IF NOT EXISTS seen_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, source_type TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE, title TEXT NOT NULL, year TEXT,
            first_seen_at TEXT NOT NULL, notified_at TEXT)'''
        with self.conn() as c:
            cur = c.cursor()
            cur.execute(schema)
            cur.execute('CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)')

    def one(self, sql, params=()):
        with self.conn() as c:
            cur = c.cursor()
            cur.execute(sql, params)
            return cur.fetchone()

    def has_url(self, url):
        sql = 'SELECT 1 FROM seen_items WHERE url=%s LIMIT 1' if self.pg else 'SELECT 1 FROM seen_items WHERE url=? LIMIT 1'
        return self.one(sql, (url,)) is not None

    def add(self, item: MovieItem, notified=False):
        now = datetime.now(timezone.utc).isoformat()
        vals = (item.source, item.source_type, item.url, item.title, item.year, now, now if notified else None)
        with self.conn() as c:
            cur = c.cursor()
            if self.pg:
                cur.execute('''INSERT INTO seen_items(source,source_type,url,title,year,first_seen_at,notified_at)
                               VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(url) DO NOTHING''', vals)
            else:
                cur.execute('''INSERT OR IGNORE INTO seen_items(source,source_type,url,title,year,first_seen_at,notified_at)
                               VALUES(?,?,?,?,?,?,?)''', vals)

    def get_state(self, key):
        sql = 'SELECT value FROM app_state WHERE key=%s' if self.pg else 'SELECT value FROM app_state WHERE key=?'
        row = self.one(sql, (key,))
        return row[0] if row else None

    def set_state(self, key, value):
        with self.conn() as c:
            cur = c.cursor()
            if self.pg:
                cur.execute('INSERT INTO app_state(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value', (key, value))
            else:
                cur.execute('INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

def abs_url(base, value):
    return urljoin(base, value.strip()) if value else None

def node_text(node):
    return ' '.join(node.get_text(' ', strip=True).split()) if node else ''

def clean_title(value):
    value = ' '.join(value.split())
    value = QUALITY_RE.sub('', value)
    value = re.sub(r'\s*\((?:19|20)\d{2}\)\s*$', '', value)
    return value.strip(' -|\n\t')

def img_url(node: Tag, base):
    img = node.find('img')
    if not img:
        return None
    for key in ('data-src', 'data-lazy-src', 'data-original', 'src'):
        val = img.get(key)
        if val and not str(val).startswith('data:'):
            return urljoin(base, str(val))
    srcset = img.get('srcset') or img.get('data-srcset')
    return urljoin(base, str(srcset).split(',')[-1].strip().split(' ')[0]) if srcset else None

class Scraper:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={'User-Agent': USER_AGENT, 'Accept-Language': 'en-US,en;q=0.9,km;q=0.8'}
        )

    async def soup(self, url):
        r = await self.client.get(url)
        r.raise_for_status()
        return BeautifulSoup(r.text, 'html.parser')

    async def close(self):
        await self.client.aclose()

    async def holly(self):
        base = 'https://hollymoviehd.cc/movies/'
        s = await self.soup(base)
        candidates = s.select('article,.item,.items .item,.movies .item,.result-item,.ml-item,.poster,.movie-item')
        if not candidates:
            candidates = [a.parent for a in s.find_all('a', href=True) if a.find('img') and a.parent]
        out, seen = [], set()
        for node in candidates:
            if not isinstance(node, Tag):
                continue
            anchors = node.find_all('a', href=True)
            a = next((x for x in anchors if x.find('img')), anchors[0] if anchors else None)
            if not a:
                continue
            href = abs_url(base, a.get('href'))
            if not href or href in seen or not urlparse(href).netloc.lower().endswith('hollymoviehd.cc'):
                continue
            path = urlparse(href).path.rstrip('/') + '/'
            if path in ('/', '/movies/') or any(x in path for x in ('/recommended/', '/genre/', '/country/', '/release/', '/tag/', '/page/', '/request/', '/login/', '/register/')):
                continue
            title = ''
            for sel in ('h1', 'h2', 'h3', '.title', '.data h3', '.name'):
                t = node.select_one(sel)
                if t and node_text(t):
                    title = clean_title(node_text(t))
                    break
            if not title:
                im = a.find('img') or node.find('img')
                title = clean_title(str((im.get('alt') or im.get('title') or '') if im else node_text(a)))
            if len(title) < 2:
                continue
            text = node_text(node)
            ym, qm = YEAR_RE.search(text or title), QUALITY_RE.search(text)
            out.append(MovieItem('HollyMovieHD', 'movie', title, href, img_url(node, base), ym.group(1) if ym else None, qm.group(1) if qm else None))
            seen.add(href)
            if len(out) >= MAX_ITEMS:
                break
        return out

    async def khdiamond(self):
        out = []
        for typ, base in [('movie', 'https://khdiamond.net/movies/'), ('series', 'https://khdiamond.net/seasons/')]:
            s = await self.soup(base)
            candidates = s.select('article,.item,.items .item,.movie,.season,.poster,.result-item')
            if not candidates:
                candidates = [a.parent for a in s.find_all('a', href=True) if a.find('img') and a.parent]
            expected = '/movies/' if typ == 'movie' else '/seasons/'
            seen, count = set(), 0
            for node in candidates:
                if not isinstance(node, Tag):
                    continue
                a = None
                for x in node.find_all('a', href=True):
                    h = abs_url(base, x.get('href')) or ''
                    p = urlparse(h).path
                    if expected in p and p.rstrip('/') not in ('/movies', '/seasons') and '/page/' not in p:
                        a = x
                        break
                if not a:
                    continue
                href = abs_url(base, a.get('href'))
                if not href or href in seen:
                    continue
                title = ''
                for sel in ('h1', 'h2', 'h3', '.title', '.name'):
                    t = node.select_one(sel)
                    if t and node_text(t):
                        title = clean_title(node_text(t))
                        break
                if not title:
                    im = a.find('img') or node.find('img')
                    title = clean_title(str((im.get('alt') or im.get('title') or '') if im else node_text(a)))
                if not title:
                    continue
                text = node_text(node)
                ym, qm = YEAR_RE.search(text), QUALITY_RE.search(text)
                out.append(MovieItem('KhDiaMonD', typ, title, href, img_url(node, base), ym.group(1) if ym else None, qm.group(1) if qm else None))
                seen.add(href)
                count += 1
                if count >= MAX_ITEMS:
                    break
        return out

    async def enrich(self, item):
        try:
            s = await self.soup(item.url)
        except Exception:
            return item
        og = s.select_one('meta[property="og:image"],meta[name="twitter:image"]')
        if og and og.get('content'):
            item.poster_url = abs_url(item.url, str(og.get('content')))
        text = ' '.join(s.get_text(' ', strip=True).split())
        if not item.year:
            m = YEAR_RE.search(text)
            item.year = m.group(1) if m else None
        if not item.quality:
            m = QUALITY_RE.search(text)
            item.quality = m.group(1) if m else None
        genres = []
        for a in s.select('a[href*="/genre/"],a[rel="tag"]'):
            label = node_text(a)
            if label and len(label) <= 40 and label not in genres:
                genres.append(label)
            if len(genres) >= 4:
                break
        if genres:
            item.category = ' / '.join(genres)
        pub = s.select_one('meta[property="article:published_time"],time[datetime]')
        if pub:
            raw = pub.get('content') or pub.get('datetime')
            if raw:
                item.published_date = str(raw)[:10]
        return item

class Telegram:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=TIMEOUT)
        self.base = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}'

    async def close(self):
        await self.client.aclose()

    def caption(self, item):
        dt = item.detected_at.astimezone(ZoneInfo(TIMEZONE)).strftime('%d %b %Y')
        category = item.category or ('Series' if item.source_type == 'series' else 'Movie')
        lines = [
            f'🎬 <b>{html.escape(item.title)}</b>',
            f'🌐 <b>Source:</b> {html.escape(item.source)}',
            f'📅 <b>Detected:</b> {dt}',
            f'🎞 <b>Year:</b> {html.escape(item.year or "N/A")}',
            f'✨ <b>Quality:</b> {html.escape(item.quality or "N/A")}',
            f'🏷 <b>Category:</b> {html.escape(category)}',
        ]
        if item.published_date:
            lines.append(f'🗓 <b>Published:</b> {html.escape(item.published_date)}')
        lines.append(f'🔗 <a href="{html.escape(item.url)}">Open Movie / Series</a>')
        return '\n'.join(lines)[:1000]

    async def send(self, item):
        cap = self.caption(item)
        if item.poster_url:
            r = await self.client.post(self.base + '/sendPhoto', data={
                'chat_id': TELEGRAM_CHAT_ID,
                'photo': item.poster_url,
                'caption': cap,
                'parse_mode': 'HTML'
            })
            if r.is_success and r.json().get('ok'):
                return
        r = await self.client.post(self.base + '/sendMessage', data={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': cap,
            'parse_mode': 'HTML',
            'disable_web_page_preview': 'false'
        })
        r.raise_for_status()
        if not r.json().get('ok'):
            raise RuntimeError('Telegram send failed')

class Service:
    def __init__(self):
        self.db = DB()
        self.scraper = Scraper()
        self.lock = asyncio.Lock()

    async def close(self):
        await self.scraper.close()

    async def collect(self):
        items, errors = [], []
        for name, fn in [('HollyMovieHD', self.scraper.holly), ('KhDiaMonD', self.scraper.khdiamond)]:
            try:
                items.extend(await fn())
            except Exception as e:
                errors.append(f'{name}: {type(e).__name__}: {e}')
                log.warning('%s unavailable: %s', name, type(e).__name__)
        return items, errors

    async def run_once(self):
        if self.lock.locked():
            return {'status': 'skipped', 'reason': 'run_in_progress'}
        async with self.lock:
            items, errors = await self.collect()
            first = self.db.get_state('initialized') != '1'
            if first and SEED_ON_FIRST_RUN:
                if not items:
                    return {'status': 'source_unavailable', 'fetched': 0, 'errors': errors}
                for i in items:
                    self.db.add(i, False)
                self.db.set_state('initialized', '1')
                return {'status': 'seeded', 'fetched': len(items), 'sent': 0, 'errors': errors}
            new = [i for i in items if not self.db.has_url(i.url)]
            if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                return {'status': 'waiting_for_telegram', 'fetched': len(items), 'pending_new': len(new), 'sent': 0, 'errors': errors}
            tg = Telegram()
            sent = 0
            try:
                for item in reversed(new):
                    item = await self.scraper.enrich(item)
                    await tg.send(item)
                    self.db.add(item, True)
                    sent += 1
            finally:
                await tg.close()
            self.db.set_state('initialized', '1')
            return {'status': 'ok', 'fetched': len(items), 'new': len(new), 'sent': sent, 'errors': errors}

service = None

async def bot_send_text(text, chat_id=None):
    token = TELEGRAM_BOT_TOKEN.strip()
    target = str(chat_id or TELEGRAM_CHAT_ID).strip()
    if not token or not target:
        return False
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f'https://api.telegram.org/bot{token}/sendMessage', data={
            'chat_id': target,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': 'true'
        })
        return r.is_success and r.json().get('ok', False)

async def setup_bot_menu(token):
    commands = [
        {'command': 'update', 'description': 'Check for new movies now'},
        {'command': 'status', 'description': 'Show monitoring status'},
        {'command': 'sources', 'description': 'Show monitored websites'},
        {'command': 'help', 'description': 'Show bot commands'},
    ]
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(f'https://api.telegram.org/bot{token}/setMyCommands', json={'commands': commands})

async def telegram_command_loop():
    global service
    offset = None
    active_token = None
    initialized_updates = False
    while True:
        try:
            token = TELEGRAM_BOT_TOKEN.strip()
            configured_chat = str(TELEGRAM_CHAT_ID).strip()
            if not token or not configured_chat:
                active_token = None
                initialized_updates = False
                await asyncio.sleep(3)
                continue

            if token != active_token:
                active_token = token
                offset = None
                initialized_updates = False
                await setup_bot_menu(token)

            async with httpx.AsyncClient(timeout=35) as client:
                if not initialized_updates:
                    r = await client.get(f'https://api.telegram.org/bot{token}/getUpdates', params={'offset': -1, 'limit': 1, 'timeout': 0})
                    data = r.json() if r.is_success else {}
                    latest = data.get('result', []) if data.get('ok') else []
                    if latest:
                        offset = latest[-1]['update_id'] + 1
                    initialized_updates = True

                r = await client.get(f'https://api.telegram.org/bot{token}/getUpdates', params={
                    'offset': offset,
                    'timeout': 25,
                    'allowed_updates': '["message"]'
                })
                if not r.is_success:
                    await asyncio.sleep(3)
                    continue
                data = r.json()
                if not data.get('ok'):
                    await asyncio.sleep(3)
                    continue

            for upd in data.get('result', []):
                offset = upd['update_id'] + 1
                msg = upd.get('message') or {}
                chat = msg.get('chat') or {}
                text = (msg.get('text') or '').strip()
                chat_id = str(chat.get('id', ''))
                if chat_id != configured_chat or not text.startswith('/'):
                    continue

                cmd = text.split()[0].split('@')[0].lower()
                if cmd == '/update':
                    await bot_send_text('🔄 <b>Checking for new movies now…</b>', chat_id)
                    result = await service.run_once() if service else {'status': 'starting'}
                    sent = int(result.get('sent', 0) or 0)
                    new = int(result.get('new', sent) or 0)
                    if result.get('status') == 'skipped':
                        reply = '⏳ A monitoring check is already running. Please try again shortly.'
                    elif sent > 0:
                        reply = f'✅ <b>Update complete</b>\nFound: {new}\nSent: {sent}'
                    else:
                        reply = '✅ <b>Update complete</b>\nNo new movies or series found.'
                    await bot_send_text(reply, chat_id)
                elif cmd == '/status':
                    running = 'Running' if service else 'Starting'
                    await bot_send_text(
                        f'🤖 <b>Movie Alert Bot</b>\nStatus: {running}\nAutomatic check: every 5 minutes\nManual check: /update',
                        chat_id
                    )
                elif cmd == '/sources':
                    await bot_send_text(
                        '🌐 <b>Monitoring Sources</b>\n✅ KhDiaMonD — Movies + Series\n⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403',
                        chat_id
                    )
                elif cmd in ('/help', '/start'):
                    await bot_send_text(
                        '🎬 <b>Movie Alert Bot Menu</b>\n/update — Check for new movies now\n/status — Monitoring status\n/sources — Monitored websites\n/help — Show this menu',
                        chat_id
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning('Telegram command loop error: %s', type(e).__name__)
            await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    service = Service()
    try:
        log.info('startup check: %s', await service.run_once())
    except Exception:
        log.exception('startup check failed')
    command_task = asyncio.create_task(telegram_command_loop())
    try:
        yield
    finally:
        command_task.cancel()
        try:
            await command_task
        except asyncio.CancelledError:
            pass
        await service.close()

app = FastAPI(title='Movie Alert Bot', lifespan=lifespan)

@app.get('/')
async def root():
    return {
        'name': 'Movie Alert Bot',
        'status': 'running',
        'telegram_configured': bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
        'monitor_interval_minutes': 5,
        'commands': ['/update', '/status', '/sources', '/help'],
        'sources': ['HollyMovieHD', 'KhDiaMonD']
    }

@app.get('/health')
async def health():
    return {'ok': True, 'telegram_configured': bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)}

@app.get('/cron-run')
async def cron_run():
    return await service.run_once()
