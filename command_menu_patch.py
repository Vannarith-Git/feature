import asyncio
import logging
import os
import time

import httpx
import redis.asyncio as redis_async

import app as core

log = logging.getLogger("movie-bot")
REDIS_URL = os.getenv("REDIS_URL", "").strip()
OFFSET_KEY = "moviebot:telegram_update_offset:v1"
rdb = redis_async.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None


def parse_command(text):
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return "", ""
    first = raw.split()[0]
    if "@" in first:
        command, mention = first.split("@", 1)
        return command.lower(), mention.lower()
    return first.lower(), ""


def menu_text():
    return (
        "🎬 <b>Movie Alert Bot Menu</b>\n"
        "/menu — Show this menu\n"
        "/update — Check for newly published movies now\n"
        "/status — Show monitoring status\n"
        "/sources — Show monitored sources\n"
        "/help — Show this menu"
    )


async def setup_bot_menu_fixed(token):
    commands = [
        {"command": "menu", "description": "Show bot menu"},
        {"command": "update", "description": "Check for new movies now"},
        {"command": "status", "description": "Show monitoring status"},
        {"command": "sources", "description": "Show monitored sources"},
        {"command": "help", "description": "Show bot commands"},
    ]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/setMyCommands",
            json={"commands": commands},
        )
        if not r.is_success or not r.json().get("ok"):
            raise RuntimeError("Telegram setMyCommands failed")


async def _load_offset():
    if rdb is None:
        return None
    try:
        raw = await rdb.get(OFFSET_KEY)
        return int(raw) if raw is not None else None
    except Exception:
        return None


async def _save_offset(offset):
    if rdb is None or offset is None:
        return
    try:
        await rdb.set(OFFSET_KEY, str(offset))
    except Exception:
        pass


async def telegram_command_loop_fixed():
    offset = await _load_offset()
    active_token = None
    bot_username = ""

    while True:
        try:
            token = core.TELEGRAM_BOT_TOKEN.strip()
            configured_chat = str(core.TELEGRAM_CHAT_ID).strip()
            if not token or not configured_chat:
                await asyncio.sleep(2)
                continue

            if token != active_token:
                active_token = token
                async with httpx.AsyncClient(timeout=20) as client:
                    me = await client.get(f"https://api.telegram.org/bot{token}/getMe")
                    if me.is_success and me.json().get("ok"):
                        bot_username = str(me.json()["result"].get("username") or "").lower()
                await setup_bot_menu_fixed(token)
                offset = await _load_offset()

            async with httpx.AsyncClient(timeout=35) as client:
                params = {
                    "timeout": 25,
                    "limit": 100,
                    "allowed_updates": '["message"]',
                }
                if offset is not None:
                    params["offset"] = offset
                r = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params=params,
                )

            if r.status_code == 409:
                log.warning("Telegram getUpdates conflict: another poller is using this bot token")
                await asyncio.sleep(5)
                continue
            if not r.is_success:
                log.warning("Telegram getUpdates HTTP %s", r.status_code)
                await asyncio.sleep(3)
                continue

            data = r.json()
            if not data.get("ok"):
                await asyncio.sleep(3)
                continue

            updates = data.get("result", [])
            if offset is None and updates:
                # On the very first run, process a recent command instead of
                # blindly discarding it. Old backlog is skipped safely.
                newest = updates[-1]
                msg = newest.get("message") or {}
                msg_ts = int(msg.get("date") or 0)
                if not ((msg.get("text") or "").startswith("/") and time.time() - msg_ts <= 180):
                    offset = newest["update_id"] + 1
                    await _save_offset(offset)
                    continue

            for upd in updates:
                offset = upd["update_id"] + 1
                await _save_offset(offset)

                msg = upd.get("message") or {}
                chat = msg.get("chat") or {}
                text = (msg.get("text") or "").strip()
                chat_id = str(chat.get("id", ""))
                if chat_id != configured_chat:
                    continue

                cmd, mention = parse_command(text)
                if not cmd:
                    continue
                if mention and bot_username and mention != bot_username:
                    # Telegram usually does not deliver commands addressed to
                    # another bot, but keep this check explicit.
                    continue

                log.info("Telegram command received: %s", cmd)

                if cmd == "/update":
                    await core.bot_send_text("🔄 <b>Checking for newly published movies now…</b>", chat_id)
                    result = await core.service.run_once() if core.service else {"status": "starting"}
                    sent = int(result.get("sent", 0) or 0)
                    new = int(result.get("new", sent) or 0)
                    if result.get("status") == "skipped":
                        reply = "⏳ A monitoring check is already running. Please try again shortly."
                    elif sent > 0:
                        reply = f"✅ <b>Update complete</b>\nFound: {new}\nSent: {sent}"
                    else:
                        reply = "✅ <b>Update complete</b>\nNo newly published movies or series found."
                    await core.bot_send_text(reply, chat_id)

                elif cmd == "/status":
                    await core.bot_send_text(
                        "🤖 <b>Movie Alert Bot</b>\n"
                        "Status: Running\n"
                        "Automatic check: every 5 minutes\n"
                        "Mode: incremental new-publication alerts\n"
                        "Manual check: /update",
                        chat_id,
                    )

                elif cmd == "/sources":
                    await core.bot_send_text(
                        "🌐 <b>Monitoring Sources</b>\n"
                        "✅ KhDiaMonD — Movies + Series\n"
                        "⚠️ HollyMovieHD — enabled, but currently blocks this server with HTTP 403",
                        chat_id,
                    )

                elif cmd in ("/menu", "/help", "/start"):
                    await core.bot_send_text(menu_text(), chat_id)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Telegram command loop error: %s", type(exc).__name__)
            await asyncio.sleep(4)


core.setup_bot_menu = setup_bot_menu_fixed
core.telegram_command_loop = telegram_command_loop_fixed
