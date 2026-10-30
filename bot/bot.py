
import os
import asyncio
import aiohttp
import logging

from datetime import datetime, timedelta, timezone
from aiohttp import web

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler

logging.basicConfig(level=logging.INFO)

E = os.environ

# ==============================
# CONFIGURATION
# ==============================

SB = E["SUPABASE_URL"].rstrip("/") + "/rest/v1"

H = {
    "apikey": E["SERVICE_KEY"],
    "Authorization": "Bearer " + E["SERVICE_KEY"],
    "Content-Type": "application/json"
}

LOG = int(E["LOG_CHANNEL"])
ADMIN = int(E["ADMIN_ID"])

HOURS = 3

app = None
source_ready = False
source_lock = asyncio.Lock()


# ==============================
# TIME
# ==============================

def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ==============================
# SUPABASE GET
# ==============================

async def get(path):

    async with aiohttp.ClientSession() as s:

        async with s.get(
            SB + path,
            headers=H
        ) as r:

            r.raise_for_status()
            return await r.json()


# ==============================
# SCHEDULE DELETE
# ==============================

async def schedule(chat, *ids):

    t = ts(
        datetime.now(timezone.utc)
        + timedelta(hours=HOURS)
    )

    data = [
        {
            "chat_id": chat,
            "message_id": i,
            "delete_at": t
        }
        for i in ids
    ]

    async with aiohttp.ClientSession() as s:

        async with s.post(
            SB + "/bot_deletes",
            headers=H,
            json=data
        ) as r:

            r.raise_for_status()


# ==============================
# RESOLVE PRIVATE CHANNEL PEER
# ==============================

async def ensure_source_peer(c):

    global source_ready

    async with source_lock:

        try:

            await c.resolve_peer(LOG)

            source_ready = True

            print(
                "SOURCE PEER RESOLVED SUCCESSFULLY:",
                LOG,
                flush=True
            )

            return True

        except Exception as e:

            source_ready = False

            print(
                "SOURCE PEER NOT READY:",
                repr(e),
                flush=True
            )

            return False


# ==============================
# CHANNEL POST HANDLER
# ==============================

async def channel_post(c, m):

    global source_ready

    print(
        "CHANNEL DETECTED:",
        m.chat.id,
        "MESSAGE ID:",
        m.id,
        flush=True
    )

    if m.chat.id != LOG:

        print(
            "CHANNEL ID DOES NOT MATCH LOG_CHANNEL!",
            flush=True
        )

        return

    print(
        "LOG CHANNEL VERIFIED!",
        flush=True
    )

    # New channel update may populate peer information
    await ensure_source_peer(c)


# ==============================
# START COMMAND
# ==============================

async def start(c, m):

    print(
        "START RECEIVED:",
        m.text,
        flush=True
    )

    try:

        # Check command
        if (
            len(m.command) < 2
            or not m.command[1].startswith("video_")
        ):

            return await m.reply(
                "🔥 Viral Video বটে স্বাগতম! "
                "ওয়েবসাইট থেকে ভিডিও লিংকে ক্লিক করুন।"
            )

        mid = int(m.command[1][6:])

        # Get post information
        r = await get(
            f"/post_links?tg_msg_id=eq.{mid}"
            "&select=posts(type)"
        )

        print(
            "DB REPLY:",
            r,
            flush=True
        )

        if not r or not isinstance(r, list):

            return await m.reply(
                "❌ ভিডিও পাওয়া যায়নি।"
            )

        post = r[0].get("posts")

        if isinstance(post, list):
            post = post[0] if post else None

        if not post:

            return await m.reply(
                "❌ ভিডিওর তথ্য পাওয়া যায়নি।"
            )

        # Premium verification
        if post.get("type") == "premium":

            username = (
                m.from_user.username
                if m.from_user else None
            )

            if not username:

                return await m.reply(
                    "🔒 Premium ব্যবহারের জন্য "
                    "Telegram username সেট করুন।"
                )

            ok = await get(
                f"/profiles?tg_username=ilike.{username}"
                "&status=eq.approved&select=id"
            )

            if not ok or not isinstance(ok, list):

                return await m.reply(
                    "🔒 প্রিমিয়াম! ওয়েবসাইটে "
                    "রেজিস্ট্রেশন করে অ্যাডমিনের "
                    "অনুমোদন নিন।"
                )

        # Check source peer
        ready = await ensure_source_peer(c)

        if not ready:

            return await m.reply(
                "⚠️ ভিডিও সার্ভার এখনো প্রস্তুত নয়। "
                "অ্যাডমিনকে জানান।"
            )

        print(
            "CHECKING SOURCE MESSAGE:",
            LOG,
            mid,
            flush=True
        )

        # Check source message
        source_msg = await c.get_messages(
            LOG,
            mid
        )

        if not source_msg or source_msg.empty:

            return await m.reply(
                "❌ Source Channel-এ ভিডিও পাওয়া যায়নি।"
            )

        if not source_msg.video and not source_msg.document:

            return await m.reply(
                "❌ এই Message-এ ভিডিও পাওয়া যায়নি।"
            )

        print(
            "SOURCE MESSAGE FOUND:",
            source_msg.id,
            flush=True
        )

        # Copy video
        print(
            "COPYING VIDEO FROM:",
            LOG,
            mid,
            flush=True
        )

        v = await c.copy_message(
            chat_id=m.chat.id,
            from_chat_id=LOG,
            message_id=mid,
            protect_content=True
        )

        print(
            "VIDEO SENT:",
            v.id,
            flush=True
        )

        # Expiry notice
        n = await m.reply(
            f"⏳ এই ভিডিও {HOURS} ঘণ্টা পর "
            "অটো ডিলিট হয়ে যাবে। আবার দেখতে হলে "
            "ওয়েবসাইট থেকে আসুন।"
        )

        # Schedule all messages
        await schedule(
            m.chat.id,
            v.id,
            n.id,
            m.id
        )

        print(
            "DELETE SCHEDULED SUCCESSFULLY",
            flush=True
        )

    except Exception as e:

        print(
            "START ERROR:",
            repr(e),
            flush=True
        )

        try:

            await m.reply(
                "⚠️ ভিডিও পাঠাতে সমস্যা হয়েছে। "
                "অ্যাডমিনকে জানান।"
            )

        except Exception as e2:

            print(
                "REPLY ERROR:",
                repr(e2),
                flush=True
            )


# ==============================
# OTHER PRIVATE MESSAGES
# ==============================

async def anymsg(c, m):

    print(
        "PRIVATE MESSAGE RECEIVED:",
        m.text,
        flush=True
    )


# ==============================
# DELETE EXPIRED MESSAGES
# ==============================

async def sweeper():

    while True:

        try:

            now = ts(datetime.now(timezone.utc))

            rows = await get(
                f"/bot_deletes?delete_at=lt.{now}"
                "&select=id,chat_id,message_id"
            )

            for d in rows:

                try:

                    await app.delete_messages(
                        int(d["chat_id"]),
                        int(d["message_id"])
                    )

                    print(
                        "MESSAGE DELETED:",
                        d["message_id"],
                        flush=True
                    )

                except Exception as e:

                    print(
                        "DELETE ERROR:",
                        repr(e),
                        flush=True
                    )

                # Remove processed row
                async with aiohttp.ClientSession() as s:

                    async with s.delete(
                        SB + f"/bot_deletes?id=eq.{d['id']}",
                        headers=H
                    ) as r:

                        r.raise_for_status()

        except Exception as e:

            print(
                "SWEEPER ERROR:",
                repr(e),
                flush=True
            )

        await asyncio.sleep(60)


# ==============================
# NEW USER NOTIFICATION
# ==============================

async def notify():

    while True:

        try:

            users = await get(
                "/profiles?notified=eq.false"
                "&select=id,email,tg_username"
            )

            for u in users:

                await app.send_message(
                    ADMIN,
                    f"🆕 নতুন ইউজার: "
                    f"{u['email']} @{u['tg_username']}"
                )

                async with aiohttp.ClientSession() as s:

                    async with s.patch(
                        SB + f"/profiles?id=eq.{u['id']}",
                        headers=H,
                        json={"notified": True}
                    ) as r:

                        r.raise_for_status()

        except Exception as e:

            print(
                "NOTIFY ERROR:",
                repr(e),
                flush=True
            )

        await asyncio.sleep(30)


# ==============================
# MAIN APPLICATION
# ==============================

async def main():

    global app

    app = Client(
        "bot",
        api_id=int(E["API_ID"]),
        api_hash=E["API_HASH"],
        bot_token=E["BOT_TOKEN"],
        in_memory=True
    )

    # Register handlers BEFORE starting
    app.add_handler(
        MessageHandler(
            start,
            filters.command("start") & filters.private
        ),
        group=0
    )

    app.add_handler(
        MessageHandler(
            anymsg,
            filters.private & ~filters.command("start")
        ),
        group=1
    )

    app.add_handler(
        MessageHandler(
            channel_post,
            filters.channel
        ),
        group=2
    )

    # Start bot
    await app.start()

    me = await app.get_me()

    print(
        "BOT CHALU:",
        me.username,
        flush=True
    )

    print(
        "EXPECTED LOG CHANNEL:",
        LOG,
        flush=True
    )

    # Try resolving existing peer
    await ensure_source_peer(app)

    # Background tasks
    asyncio.create_task(notify())
    asyncio.create_task(sweeper())

    # HTTP health server
    w = web.Application()

    async def health(request):

        return web.Response(
            text="Viral Video Bot is Running",
            status=200
        )

    w.router.add_get("/", health)
    w.router.add_get("/health", health)

    rn = web.AppRunner(w)

    await rn.setup()

    await web.TCPSite(
        rn,
        "0.0.0.0",
        int(E.get("PORT", 10000))
    ).start()

    print(
        "HTTP HEALTH SERVER STARTED",
        flush=True
    )

    await asyncio.Event().wait()


# ==============================
# RUN
# ==============================

if __name__ == "__main__":

    asyncio.run(main())
