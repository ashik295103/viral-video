
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

SB = E["SUPABASE_URL"] + "/rest/v1"

H = {
    "apikey": E["SERVICE_KEY"],
    "Authorization": "Bearer " + E["SERVICE_KEY"],
    "Content-Type": "application/json"
}

LOG = E["LOG_CHANNEL"]
ADMIN = int(E["ADMIN_ID"])

HOURS = 3

app = None


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def get(path):
    async with aiohttp.ClientSession() as s:
        async with s.get(SB + path, headers=H) as r:
            r.raise_for_status()
            return await r.json()


async def schedule(chat, *ids):
    t = ts(
        datetime.now(timezone.utc) +
        timedelta(hours=HOURS)
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


# Channel detection handler
async def channel_post(c, m):
    print(
        "CHANNEL DETECTED:",
        m.chat.id,
        "MESSAGE ID:",
        m.id,
        flush=True
    )

    if m.chat.id == LOG:
        print("LOG CHANNEL VERIFIED!", flush=True)
    else:
        print("CHANNEL ID DOES NOT MATCH LOG_CHANNEL!", flush=True)


# Start command
async def start(c, m):
    print("START PELAM:", m.text, flush=True)

    try:
        if (
            len(m.command) < 2
            or not m.command[1].startswith("video_")
        ):
            return await m.reply(
                "🔥 Viral Video বটে স্বাগতম! "
                "ওয়েবসাইট থেকে ভিডিও লিংকে ক্লিক করুন।"
            )

        mid = int(m.command[1][6:])

        r = await get(
            f"/post_links?tg_msg_id=eq.{mid}&select=posts(type)"
        )

        print("DB REPLY:", r, flush=True)

        if not r or not isinstance(r, list):
            return await m.reply("❌ ভিডিও পাওয়া যায়নি।")

        if not r[0].get("posts"):
            return await m.reply("❌ ভিডিওর তথ্য পাওয়া যায়নি।")

        if r[0]["posts"]["type"] == "premium":

            u = m.from_user.username or "-"

            ok = await get(
                f"/profiles?tg_username=ilike.{u}"
                "&status=eq.approved&select=id"
            )

            if not ok or not isinstance(ok, list):
                return await m.reply(
                    "🔒 প্রিমিয়াম! ওয়েবসাইটে "
                    "রেজিস্ট্রেশনের সময় এই Telegram "
                    "username দিন এবং অ্যাডমিনের অনুমোদন নিন।"
                )

        print("COPYING VIDEO FROM:", LOG, mid, flush=True)

        v = await c.copy_message(
            m.chat.id,
            LOG,
            mid,
            protect_content=True
        )

        n = await m.reply(
            f"⏳ এই ভিডিও {HOURS} ঘণ্টা পর "
            "অটো ডিলিট হয়ে যাবে। আবার দেখতে হলে "
            "ওয়েবসাইট থেকে আসুন।"
        )

        await schedule(
            m.chat.id,
            v.id,
            n.id,
            m.id
        )

    except Exception as e:

        print("START ERROR:", repr(e), flush=True)

        try:
            await m.reply(
                "⚠️ এরর: " + str(e)[:200]
            )
        except Exception as e2:
            print("REPLY ERROR:", repr(e2), flush=True)


# Other private messages
async def anymsg(c, m):
    print(
        "MESSAGE ESECHE:",
        m.text,
        flush=True
    )


# Delete expired messages
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
                        d["chat_id"],
                        d["message_id"]
                    )

                except Exception as e:
                    print("DELETE ERROR:", repr(e))

                async with aiohttp.ClientSession() as s:
                    async with s.delete(
                        SB + f"/bot_deletes?id=eq.{d['id']}",
                        headers=H
                    ) as r:
                        r.raise_for_status()

        except Exception as e:
            print("SWEEPER ERROR:", repr(e))

        await asyncio.sleep(60)


# New user notification
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
            print("NOTIFY ERROR:", repr(e))

        await asyncio.sleep(30)


# Main application
async def main():

    global app

    app = Client(
        "bot",
        api_id=int(E["API_ID"]),
        api_hash=E["API_HASH"],
        bot_token=E["BOT_TOKEN"],
        in_memory=True
    )

    # Private start command
    app.add_handler(
        MessageHandler(
            start,
            filters.command("start") & filters.private
        ),
        group=0
    )

    # Other private messages
    app.add_handler(
        MessageHandler(
            anymsg,
            filters.private
        ),
        group=1
    )

    # Channel detection
    app.add_handler(
        MessageHandler(
            channel_post,
            filters.channel
        ),
        group=2
    )

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

    asyncio.create_task(notify())
    asyncio.create_task(sweeper())

    # Render HTTP health check
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

    print("HTTP HEALTH SERVER STARTED", flush=True)

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
