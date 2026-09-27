import html
import os
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import app as core

REDIS_URL = os.getenv("REDIS_URL", "").strip()
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "").strip()
CONFIG_ENCRYPTION_KEY = os.getenv("CONFIG_ENCRYPTION_KEY", "").strip()

rdb = redis.from_url(REDIS_URL, decode_responses=True)
fernet = Fernet(CONFIG_ENCRYPTION_KEY.encode())
app = core.app

# Replace the original JSON homepage and public cron route with the setup UI + Redis-backed config route.
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) not in ("/", "/cron-run")]


def require_admin(value: str | None):
    if not ADMIN_SECRET or value != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid setup password")


def enc(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def dec(value: str | None) -> str:
    if not value:
        return ""
    try:
        return fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


async def get_config():
    cfg = await rdb.hgetall("moviebot:config")
    return dec(cfg.get("telegram_bot_token")), dec(cfg.get("telegram_chat_id")), cfg.get("updated_at")


async def apply_config_to_core():
    token, chat_id, _ = await get_config()
    core.TELEGRAM_BOT_TOKEN = token
    core.TELEGRAM_CHAT_ID = chat_id
    return token, chat_id


class TelegramSettings(BaseModel):
    bot_token: str
    chat_id: str


class TokenOnly(BaseModel):
    bot_token: str


PAGE = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Movie Alert Bot</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f7fa;color:#102331;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}.wrap{max-width:850px;margin:auto;padding:24px 16px 60px}.hero{background:linear-gradient(135deg,#0d2941,#15577f);color:#fff;border-radius:24px;padding:28px;box-shadow:0 18px 50px #17354d25}.hero h1{margin:0 0 8px}.hero p{opacity:.84;line-height:1.5}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:18px}.stat{background:#ffffff18;border-radius:15px;padding:13px}.stat b{display:block;font-size:17px}.card{background:#fff;border:1px solid #dce6ed;border-radius:21px;padding:22px;margin-top:18px;box-shadow:0 8px 28px #17354d12}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.between{justify-content:space-between}.muted{color:#667887}.pill{display:inline-flex;gap:7px;align-items:center;background:#edf8f0;color:#17672c;border-radius:999px;padding:8px 12px;font-weight:700}.dot{width:8px;height:8px;border-radius:50%;background:#2da44e}button{border:0;border-radius:12px;padding:12px 15px;font-weight:750;cursor:pointer}.primary{background:#0d6efd;color:#fff}.secondary{background:#edf3f7;color:#163247}.modal{display:none;position:fixed;inset:0;background:#07152199;align-items:center;justify-content:center;padding:16px;z-index:10}.modal.open{display:flex}.panel{width:min(520px,100%);background:#fff;border-radius:23px;padding:23px;box-shadow:0 24px 80px #0005}.close{float:right;background:#eef3f6;color:#41596a;padding:8px 10px}label{display:block;font-size:13px;font-weight:800;margin:15px 0 7px}input{width:100%;border:1px solid #cddae3;border-radius:12px;padding:13px;font-size:16px;outline:none}.pw{position:relative}.pw button{position:absolute;right:6px;top:6px;padding:7px 9px;background:#edf3f7}.note{background:#f4f8fb;color:#486174;padding:11px 12px;border-radius:12px;margin-top:12px;font-size:13px;line-height:1.45}.result{display:none;margin-top:12px;padding:11px 12px;border-radius:12px}.ok{display:block;background:#eaf7ed;color:#17672c}.err{display:block;background:#fff0f0;color:#982121}.groups{display:grid;gap:8px;margin-top:10px}.group{display:flex;justify-content:space-between;align-items:center;gap:8px;background:#f4f8fb;border-radius:10px;padding:10px}.group button{padding:8px 10px}.source{padding:10px 0;border-bottom:1px solid #edf1f4}.source:last-child{border:0}.commands{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.command{background:#f4f8fb;border-radius:12px;padding:12px}.command b{display:block;margin-bottom:4px}@media(max-width:620px){.stats,.commands{grid-template-columns:1fr}.hero{padding:22px}.panel{padding:19px}}
</style></head><body><div class='wrap'><div class='hero'><h1>🎬 Movie Alert Bot</h1><p>Automatic new movie and series alerts with poster and clean Telegram formatting.</p><div class='stats'><div class='stat'><small>Status</small><b>Running</b></div><div class='stat'><small>Schedule</small><b>Every 5 min</b></div><div class='stat'><small>Region</small><b>Singapore</b></div></div></div>
<div class='card'><div class='row between'><div><h2 style='margin:0 0 6px'>Telegram Delivery</h2><div id='tgStatus' class='muted'>Checking…</div></div><button class='primary' onclick='openSetup()'>⚙️ Telegram Setup</button></div><div class='note'>Bot token is encrypted before storage and is never shown again after saving.</div></div>
<div class='card'><h2 style='margin-top:0'>Bot Commands</h2><div class='commands'><div class='command'><b>/update</b><span class='muted'>Check for new movies immediately</span></div><div class='command'><b>/status</b><span class='muted'>Show monitoring status</span></div><div class='command'><b>/sources</b><span class='muted'>Show monitored websites</span></div><div class='command'><b>/help</b><span class='muted'>Show bot menu</span></div></div></div>
<div class='card'><h2 style='margin-top:0'>Sources</h2><div class='source'>✅ <b>KhDiaMonD</b> — Movies + Series</div><div class='source'>⚠️ <b>HollyMovieHD</b> — Enabled, but currently blocks Render server requests with HTTP 403.</div><div class='row' style='margin-top:14px'><button class='secondary' onclick='runNow()'>Run Check Now</button><button class='secondary' onclick='refreshStatus()'>Refresh</button></div><div id='runResult' class='result'></div></div></div>
<div id='modal' class='modal'><div class='panel'><button class='close' onclick='closeSetup()'>✕</button><h2 style='margin-top:0'>Telegram Bot Setup</h2><p class='muted'>Enter the values here. Do not send your bot token in chat.</p><label>Setup Password</label><div class='pw'><input id='admin' type='password' autocomplete='off' placeholder='Setup password'><button onclick="toggle('admin')">Show</button></div><label>Telegram Bot Token</label><div class='pw'><input id='token' type='password' autocomplete='off' placeholder='123456789:AA…'><button onclick="toggle('token')">Show</button></div><label>Telegram Group / Channel ID</label><input id='chat' type='text' autocomplete='off' placeholder='-1001234567890 or @channelusername'><div class='row' style='margin-top:14px'><button class='secondary' onclick='findGroups()'>Find My Groups</button><button class='primary' onclick='saveConfig()'>Save & Verify</button></div><div id='groups' class='groups'></div><div id='setupResult' class='result'></div><div class='note'>Add the bot to the target group/channel first. For channels, allow posting messages and photos.</div></div></div>
<script>
const $=x=>document.getElementById(x);function openSetup(){$('modal').classList.add('open')}function closeSetup(){$('modal').classList.remove('open')}function toggle(id){let e=$(id);e.type=e.type==='password'?'text':'password'}function msg(id,t,ok){let e=$(id);e.className='result '+(ok?'ok':'err');e.textContent=t}function admin(){return $('admin').value.trim()}
async function refreshStatus(){try{let r=await fetch('/api/status'),j=await r.json();$('tgStatus').innerHTML=j.telegram.configured?'<span class="pill"><span class="dot"></span>Connected</span> &nbsp;'+(j.telegram.chat_id_masked||''):'Not configured yet'}catch(e){$('tgStatus').textContent='Status unavailable'}}
async function saveConfig(){let token=$('token').value.trim(),chat=$('chat').value.trim();if(!admin()||!token||!chat)return msg('setupResult','Fill Setup Password, Bot Token and Chat ID.',false);msg('setupResult','Verifying Telegram…',true);try{let r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Secret':admin()},body:JSON.stringify({bot_token:token,chat_id:chat})}),j=await r.json();if(!r.ok)throw new Error(j.detail||'Save failed');$('token').value='';msg('setupResult','Saved. Bot @'+(j.bot_username||'unknown')+' → '+(j.chat_title||'Telegram chat'),true);refreshStatus()}catch(e){msg('setupResult',e.message,false)}}
async function findGroups(){let token=$('token').value.trim();if(!admin()||!token)return msg('setupResult','Enter Setup Password and Bot Token first.',false);try{let r=await fetch('/api/detect-groups',{method:'POST',headers:{'Content-Type':'application/json','X-Admin-Secret':admin()},body:JSON.stringify({bot_token:token})}),j=await r.json();if(!r.ok)throw new Error(j.detail||'Unable to detect groups');$('groups').innerHTML='';if(!j.groups.length)return msg('setupResult','No groups found. Send one message in the group, then try again.',false);j.groups.forEach(g=>{let d=document.createElement('div');d.className='group';let s=document.createElement('span');s.textContent=g.title+' · '+g.id;let b=document.createElement('button');b.className='secondary';b.textContent='Use';b.onclick=()=>{$('chat').value=g.id};d.append(s,b);$('groups').appendChild(d)});msg('setupResult','Select the target group below.',true)}catch(e){msg('setupResult',e.message,false)}}
async function runNow(){try{let r=await fetch('/cron-run',{method:'POST'}),j=await r.json();msg('runResult',JSON.stringify(j),r.ok)}catch(e){msg('runResult',e.message,false)}}refreshStatus();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def home():
    return PAGE


@app.get("/api/status")
async def status():
    token, chat_id, updated = await get_config()
    if token and chat_id:
        core.TELEGRAM_BOT_TOKEN = token
        core.TELEGRAM_CHAT_ID = chat_id
    masked = chat_id[:5] + "…" + chat_id[-4:] if len(chat_id) > 10 else ("••••" if chat_id else "")
    return {"ok": True, "telegram": {"configured": bool(token and chat_id), "chat_id_masked": masked, "updated_at": updated}}


@app.post("/api/settings")
async def save_settings(payload: TelegramSettings, x_admin_secret: str | None = Header(default=None)):
    require_admin(x_admin_secret)
    token = payload.bot_token.strip()
    chat_id = payload.chat_id.strip()
    if len(token) < 20 or not chat_id:
        raise HTTPException(status_code=400, detail="Invalid Telegram settings")
    base = f"https://api.telegram.org/bot{token}"
    async with httpx.AsyncClient(timeout=20) as client:
        me = await client.get(base + "/getMe")
        if not me.is_success or not me.json().get("ok"):
            raise HTTPException(status_code=400, detail="Invalid Telegram bot token")
        chat = await client.post(base + "/getChat", data={"chat_id": chat_id})
        if not chat.is_success or not chat.json().get("ok"):
            raise HTTPException(status_code=400, detail="Bot cannot access this Chat/Group ID. Add the bot to the group/channel first.")
        test = await client.post(base + "/sendMessage", data={"chat_id": chat_id, "text": "✅ Movie Alert Bot connected successfully.\n\nNotifications are ready."})
        if not test.is_success or not test.json().get("ok"):
            raise HTTPException(status_code=400, detail="Telegram test message failed")
    await rdb.hset("moviebot:config", mapping={"telegram_bot_token": enc(token), "telegram_chat_id": enc(chat_id), "updated_at": datetime.now(timezone.utc).isoformat()})
    core.TELEGRAM_BOT_TOKEN = token
    core.TELEGRAM_CHAT_ID = chat_id
    try:
        await core.setup_bot_menu(token)
    except Exception:
        pass
    me_j = me.json()["result"]
    chat_j = chat.json()["result"]
    return {"ok": True, "bot_username": me_j.get("username"), "chat_title": chat_j.get("title") or chat_j.get("username") or str(chat_j.get("id"))}


@app.post("/api/detect-groups")
async def detect_groups(payload: TokenOnly, x_admin_secret: str | None = Header(default=None)):
    require_admin(x_admin_secret)
    token = payload.bot_token.strip()
    base = f"https://api.telegram.org/bot{token}"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(base + "/getUpdates", params={"limit": 100})
    if not r.is_success or not r.json().get("ok"):
        raise HTTPException(status_code=400, detail="Invalid token or Telegram updates unavailable")
    groups = []
    seen = set()
    for upd in r.json().get("result", []):
        obj = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member") or {}
        chat = obj.get("chat") if isinstance(obj, dict) else None
        if chat and chat.get("type") in ("group", "supergroup", "channel"):
            cid = str(chat.get("id"))
            if cid not in seen:
                seen.add(cid)
                groups.append({"id": cid, "title": chat.get("title") or chat.get("username") or "Telegram Chat", "type": chat.get("type")})
    return {"ok": True, "groups": groups[-20:]}


@app.post("/cron-run")
async def cron_run():
    await apply_config_to_core()
    if core.service is None:
        raise HTTPException(status_code=503, detail="Service is starting")
    return await core.service.run_once()
