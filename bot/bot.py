
import os
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp
from aiohttp import web

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler


# ==============================
# CONFIGURATION
# ==============================

E = os.environ

API_ID = int(E["API_ID"])
API_HASH = E["API_HASH"]
BOT_TOKEN = E["BOT_TOKEN"]

SUPABASE_URL = E["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = E["SERVICE_KEY"]

SB = SUPABASE_URL + "/rest/v1"

LOG = int(E["LOG_CHANNEL"])
ADMIN_ID = int(E["ADMIN_ID"])

SOURCE_INVITE_LINK = E["SOURCE_INVITE_LINK"]

HOURS = 3
DELETE_SECONDS = HOURS * 60 * 60

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

source_ready = False
http_session = None


# ==============================
# SUPABASE
# ==============================

def sb_headers():
    return {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }


async def get(path):
    async with http_session.get(
        SB + path,
        headers=sb_headers()
    ) as response:

        result = await response.json()

        if response.status >= 400:
            raise Exception(f"Supabase GET {response.status}: {result}")

        return result


async def insert(path, data):
    async with http_session.post(
        SB + path,
        headers=sb_headers(),
        json=data
    ) as response:

        result = await response.json()

        if response.status >= 400:
            raise Exception(f"Supabase INSERT {response.status}: {result}")

        return result


async def patch(path, data):
    async with http_session.patch(
        SB + path,
        headers=sb_headers(),
        json=data
    ) as response:

        result = await response.json()

        if response.status >= 400:
            raise Exception(f"Supabase PATCH {response.status}: {result}")

        return result


async def delete(path):
    async with http_session.delete(
        SB + path,
        headers=sb_headers()
    ) as response:

        result = await response.text()

        if response.status >= 400:
            raise Exception(f"Supabase DELETE {response.status}: {result}")

        return result


# ==============================
# SOURCE CHANNEL RESOLUTION
# ==============================

async def ensure_source_peer(c):
    global source_ready

    try:
        print("RESOLVING PRIVATE SOURCE CHANNEL...", flush=True)

        chat = await c.get_chat(SOURCE_INVITE_LINK)

        print(
            "PRIVATE CHANNEL FOUND:",
            chat.id,
            getattr(chat, "title", "Unknown"),
            flush=True
        )

        if int(chat.id) != LOG:
            raise ValueError(
                f"CHANNEL ID MISMATCH: expected {LOG}, got {chat.id}"
            )

        await c.resolve_peer(LOG)

        print("SOURCE PEER RESOLVED SUCCESSFULLY!", flush=True)

        source_ready = True
        return True

    except Exception as e:
        source_ready = False

        print(
            "PRIVATE CHANNEL RESOLUTION ERROR:",
            repr(e),
            flush=True
        )

        return False


# ==============================
# AUTO DELETE SCHEDULER
# ==============================

async def schedule(chat_id, *message_ids):

    delete_at = (
        datetime.now(timezone.utc) +
        timedelta(seconds=DELETE_SECONDS)
    ).isoformat()

    rows = []

    for message_id in message_ids:
        rows.append({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": delete_at
        })

    if rows:
        await insert("bot_deletes", rows)

        print(
            f"SCHEDULED {len(rows)} MESSAGE(S) FOR DELETION",
            flush=True
        )


# ==============================
# DELETE WORKER
# ==============================

async def sweeper(c):

    print("DELETE WORKER STARTED", flush=True)

    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()

            rows = await get(
                "/bot_deletes"
                "?delete_at=lte." + quote(now, safe="") +
                "&select=id,chat_id,message_id"
            )

            for row in rows:

                try:
                    await c.delete_messages(
                        int(row["chat_id"]),
                        int(row["message_id"])
                    )

                    print(
                        "MESSAGE DELETED:",
                        row["message_id"],
                        flush=True
                    )

                except Exception as e:
                    print(
                        "DELETE MESSAGE ERROR:",
                        repr(e),
                        flush=True
                    )

                finally:
                    try:
                        await delete(
                            "/bot_deletes?id=eq." +
                            str(row["id"])
                        )
                    except Exception as e:
                        print(
                            "DELETE DB ROW ERROR:",
                            repr(e),
                            flush=True
                        )

        except Exception as e:
            print("SWEEPER ERROR:", repr(e), flush=True)

        await asyncio.sleep(60)


# ==============================
# ADMIN NOTIFICATIONS
# ==============================

async def notify(c):

    print("PROFILE NOTIFICATION WORKER STARTED", flush=True)

    while True:
        try:
            rows = await get(
                "/profiles"
                "?notified=eq.false"
                "&select=id,email,tg_username,status"
            )

            for row in rows:

                message = (
                    "🔔 নতুন Profile Notification\n\n"
                    f"Email: {row.get('email') or 'N/A'}\n"
                    f"Telegram: @{row.get('tg_username') or 'N/A'}\n"
                    f"Status: {row.get('status') or 'N/A'}"
                )

                try:
                    await c.send_message(
                        ADMIN_ID,
                        message
                    )

                    await patch(
                        "/profiles?id=eq." + str(row["id"]),
                        {"notified": True}
                    )

                    print(
                        "ADMIN NOTIFICATION SENT:",
                        row["id"],
                        flush=True
                    )

                except Exception as e:
                    print(
                        "NOTIFICATION ERROR:",
                        repr(e),
                        flush=True
                    )

        except Exception as e:
            print("NOTIFY WORKER ERROR:", repr(e), flush=True)

        await asyncio.sleep(60)


# ==============================
# START COMMAND
# ==============================

async def start(c, m):

    print("START RECEIVED:", m.text, flush=True)

    try:
        parts = (m.text or "").split()

        if len(parts) < 2:
            await m.reply_text(
                "👋 স্বাগতম!\n\nভিডিও দেখতে সঠিক লিংক ব্যবহার করুন।"
            )
            return

        payload = parts[1]

        if not payload.startswith("video_"):
            await m.reply_text("❌ ভুল ভিডিও লিংক।")
            return

        mid_text = payload.replace("video_", "", 1)

        if not mid_text.isdigit():
            await m.reply_text("❌ ভুল ভিডিও ID।")
            return

        mid = int(mid_text)

        # Check video in database
        records = await get(
            "/post_links"
            "?tg_msg_id=eq." + str(mid) +
            "&select=posts(type)"
        )

        print("DB REPLY:", records, flush=True)

        if not records:
            await m.reply_text("❌ ভিডিওটি পাওয়া যায়নি।")
            return

        post_info = records[0].get("posts") or {}
        post_type = post_info.get("type", "normal")

        # Premium check
        if post_type == "premium":

            username = m.from_user.username

            if not username:
                await m.reply_text(
                    "⚠️ Premium ভিডিও দেখতে Telegram Username সেট করুন।"
                )
                return

            approved = await get(
                "/profiles"
                "?tg_username=ilike." + quote(username, safe="") +
                "&status=eq.approved"
                "&select=id"
            )

            if not approved:
                await m.reply_text(
                    "🔒 এটি Premium ভিডিও।\n\n"
                    "ভিডিও দেখতে আপনার Premium অনুমোদন প্রয়োজন।"
                )
                return

        # Check source channel
        if not source_ready:
            ready = await ensure_source_peer(c)

            if not ready:
                await m.reply_text(
                    "⚠️ ভিডিও সার্ভার এখনো প্রস্তুত নয়। "
                    "অ্যাডমিনকে জানান।"
                )
                return

        # Copy video
        print(
            "COPYING VIDEO FROM:",
            LOG,
            mid,
            flush=True
        )

        copied = await c.copy_message(
            chat_id=m.chat.id,
            from_chat_id=LOG,
            message_id=mid,
            protect_content=True
        )

        notice = await m.reply_text(
            "⏳ এই ভিডিওটি ৩ ঘণ্টা পর স্বয়ংক্রিয়ভাবে মুছে যাবে।"
        )

        await schedule(
            m.chat.id,
            copied.id,
            notice.id,
            m.id
        )

        print(
            "VIDEO SENT SUCCESSFULLY:",
            copied.id,
            flush=True
        )

    except Exception as e:

        print("START ERROR:", repr(e), flush=True)

        try:
            await m.reply_text(
                "❌ ভিডিও পাঠাতে সমস্যা হয়েছে। "
                "কিছুক্ষণ পর আবার চেষ্টা করুন।"
            )
        except Exception:
            pass


# ==============================
# CHANNEL POST DETECTION
# ==============================

async def channel_detector(c, m):

    global source_ready

    try:
        print(
            "CHANNEL DETECTED:",
            m.chat.id,
            m.chat.title,
            "MESSAGE:",
            m.id,
            flush=True
        )

        if int(m.chat.id) == LOG:

            try:
                await c.resolve_peer(LOG)

                source_ready = True

                print(
                    "CHANNEL PEER READY FROM UPDATE!",
                    flush=True
                )

            except Exception as e:
                print(
                    "CHANNEL PEER RESOLVE ERROR:",
                    repr(e),
                    flush=True
                )

    except Exception as e:
        print("CHANNEL DETECTOR ERROR:", repr(e), flush=True)


# ==============================
# OTHER PRIVATE MESSAGES
# ==============================

async def private_messages(c, m):

    # Reserved for other private-message handling.
    pass


# ==============================
# HEALTH SERVER
# ==============================

async def health(request):

    return web.json_response({
        "status": "running",
        "source_ready": source_ready
    })


async def start_health_server():

    app = web.Application()

    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)

    await runner.setup()

    port = int(E.get("PORT", 10000))

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    print(
        "HTTP HEALTH SERVER STARTED ON PORT:",
        port,
        flush=True
    )


# ==============================
# MAIN
# ==============================

async def main():

    global http_session

    timeout = aiohttp.ClientTimeout(total=30)

    http_session = aiohttp.ClientSession(
        timeout=timeout
    )

    c = Client(
        "viral_video_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        in_memory=True
    )

    # Register handlers
    c.add_handler(
        MessageHandler(
            start,
            filters.private & filters.command("start")
        ),
        group=0
    )

    c.add_handler(
        MessageHandler(
            private_messages,
            filters.private & ~filters.command("start")
        ),
        group=1
    )

    c.add_handler(
        MessageHandler(
            channel_detector,
            filters.channel
        ),
        group=2
    )

    await c.start()

    me = await c.get_me()

    print(
        "BOT STARTED:",
        me.username,
        flush=True
    )

    print(
        "SOURCE CHANNEL ID:",
        LOG,
        flush=True
    )

    # Resolve private source channel
    await ensure_source_peer(c)

    # Background workers
    asyncio.create_task(sweeper(c))
    asyncio.create_task(notify(c))

    # Render health server
    await start_health_server()

    print("ALL SERVICES STARTED", flush=True)

    # Keep bot running
    await asyncio.Event().wait()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except Exception as e:
        print("FATAL ERROR:", repr(e), flush=True)
