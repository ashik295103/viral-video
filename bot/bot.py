import os, time, asyncio, aiohttp, logging
from urllib.parse import quote
from datetime import datetime, timedelta, timezone
from aiohttp import web
from pyrogram import Client, filters, enums
from pyrogram.handlers import MessageHandler

logging.basicConfig(level=logging.INFO)

E = os.environ
SB = E["SUPABASE_URL"] + "/rest/v1"
KEY = E["SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}
LOG = int(E["LOG_CHANNEL"])  # প্রাইভেট চ্যানেলের আইডি, যেমন -1001234567890
ADMIN = int(E["ADMIN_ID"])
HOURS = 3
STRICT = E.get("STRICT_LINK") == "1"  # 1 দিলে /link না করা ইউজার প্রিমিয়াম পাবে না (সবাই লিংক করার পর চালু করুন)
COOLDOWN = 8  # একই ইউজার কত সেকেন্ডে একবার রিকোয়েস্ট দিতে পারবে
LAST = {}
app = None


def too_fast(uid):
    now = time.monotonic()
    if now - LAST.get(uid, 0) < COOLDOWN:
        return True
    LAST[uid] = now
    if len(LAST) > 5000:  # মেমরি ফুরিয়ে যাওয়া ঠেকাতে পুরনো এন্ট্রি মুছি
        for k in [k for k, v in LAST.items() if now - v > 300]:
            LAST.pop(k, None)
    return False


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


async def get(path):
    async with aiohttp.ClientSession() as s:
        async with s.get(SB + path, headers=H) as r:
            return await r.json()


async def schedule(chat, *ids):
    t = ts(datetime.now(timezone.utc) + timedelta(hours=HOURS))
    async with aiohttp.ClientSession() as s:
        await s.post(
            SB + "/bot_deletes",
            headers=H,
            json=[{"chat_id": chat, "message_id": i, "delete_at": t} for i in ids],
        )


async def resolve_channel():
    """চ্যানেল resolve করে peer ক্যাশে রাখে। সফল হলে True।"""
    try:
        ch = await app.get_chat(LOG)
        print("CHANNEL OK:", ch.title, flush=True)
        return True
    except Exception as e:
        print("CHANNEL ERROR:", repr(e), flush=True)
        return False


async def copy_via_api(to_chat, mid):
    """Bot API দিয়ে কপি করে। এতে Pyrogram-এর peer ক্যাশ লাগে না, প্রাইভেট চ্যানেলেও চলে।"""
    url = f"https://api.telegram.org/bot{E['BOT_TOKEN']}/copyMessage"
    payload = {
        "chat_id": to_chat,
        "from_chat_id": LOG,
        "message_id": mid,
        "protect_content": True,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as r:
            data = await r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "copyMessage failed"))
    return data["result"]["message_id"]


async def start(c, m):
    print("START PELAM:", m.text, flush=True)
    try:
        if len(m.command) < 2 or not m.command[1].startswith("video_"):
            return await m.reply("🔥 Viral Video বটে স্বাগতম! ওয়েবসাইট থেকে ভিডিও লিংকে ক্লিক করুন।")
        if m.from_user.id != ADMIN and too_fast(m.from_user.id):
            return await m.reply("⏳ একটু অপেক্ষা করুন, কয়েক সেকেন্ড পর আবার চেষ্টা করুন।")
        # রক্ষণাবেক্ষণ চালু থাকলে অ্যাডমিন ছাড়া কাউকে ভিডিও দেওয়া হবে না
        st = await get("/settings?id=eq.1&select=maintenance,maintenance_msg")
        if isinstance(st, list) and st and st[0].get("maintenance") and m.from_user.id != ADMIN:
            return await m.reply("🛠️ রক্ষণাবেক্ষণের কাজ চলছে। খুব দ্রুত সমাধান করা হবে। সাময়িক সময়ের জন্য আমরা দুঃখিত।")
        mid = int(m.command[1][6:])
        r = await get(f"/post_links?tg_msg_id=eq.{mid}&select=posts(type)")
        print("DB REPLY:", r, flush=True)
        if not r or not isinstance(r, list):
            return await m.reply("❌ ভিডিও পাওয়া যায়নি।")
        if r[0]["posts"]["type"] == "premium":
            # ১) আসল Telegram ID দিয়ে যাচাই (/link করা অ্যাকাউন্ট) — সবচেয়ে নিরাপদ
            ok = await get(f"/profiles?tg_id=eq.{m.from_user.id}&status=eq.approved&select=id")
            if not (isinstance(ok, list) and ok):
                # ২) এখনো /link করেনি এমন পুরনো ইউজারদের জন্য exact username মিল (STRICT_LINK=1 দিলে বন্ধ)
                u = (m.from_user.username or "").lower()
                if not STRICT and u:
                    ok = await get(f"/profiles?tg_username=eq.{quote(u, safe='')}&tg_id=is.null&status=eq.approved&select=id")
                else:
                    ok = []
            if not (isinstance(ok, list) and ok):
                return await m.reply("🔒 প্রিমিয়াম! ওয়েবসাইটে অ্যাকাউন্ট করে অ্যাডমিনের অনুমোদন নিন। এরপর সাইটে লগইন করে \"🔗 Telegram\" বাটন থেকে কোড নিয়ে এখানে /link কোড পাঠান।")
        vid = await copy_via_api(m.chat.id, mid)
        n = await m.reply(f"⏳ এই ভিডিও {HOURS} ঘণ্টা পর অটো ডিলিট হয়ে যাবে। আবার দেখতে হলে ওয়েবসাইট থেকে আসুন।")
        await schedule(m.chat.id, vid, n.id, m.id)
    except Exception as e:
        print("START ERROR:", repr(e), flush=True)
        try:
            await m.reply("⚠️ একটু সমস্যা হয়েছে, কিছুক্ষণ পর আবার চেষ্টা করুন।")  # ভেতরের এরর ইউজারকে দেখানো হয় না
        except Exception as e2:
            print("REPLY ERROR:", repr(e2), flush=True)


async def link(c, m):
    try:
        if too_fast(("link", m.from_user.id)):
            return await m.reply("⏳ একটু অপেক্ষা করুন, কয়েক সেকেন্ড পর আবার চেষ্টা করুন।")
        if len(m.command) < 2:
            return await m.reply("ওয়েবসাইটে লগইন করে \"🔗 Telegram\" বাটন থেকে কোড নিন, তারপর লিখুন: /link আপনার_কোড")
        code = m.command[1].strip().upper()
        if not code.isalnum() or len(code) > 16:
            return await m.reply("❌ কোডটি ঠিক নয়।")
        now = ts(datetime.now(timezone.utc))
        r = await get(f"/profiles?link_code=eq.{quote(code, safe='')}&link_code_exp=gt.{now}&select=id")
        if not (isinstance(r, list) and r):
            return await m.reply("❌ কোড ভুল অথবা মেয়াদ শেষ। ওয়েবসাইট থেকে নতুন কোড নিন।")
        async with aiohttp.ClientSession() as s:
            async with s.patch(
                SB + f"/profiles?id=eq.{r[0]['id']}",
                headers=H,
                json={"tg_id": m.from_user.id, "link_code": None, "link_code_exp": None},
            ) as resp:
                if resp.status >= 300:
                    return await m.reply("❌ এই Telegram অ্যাকাউন্ট আগে থেকেই অন্য একটি অ্যাকাউন্টের সাথে যুক্ত।")
        await m.reply("✅ আপনার Telegram সফলভাবে যুক্ত হয়েছে।")
    except Exception as e:
        print("LINK ERROR:", repr(e), flush=True)
        try:
            await m.reply("⚠️ একটু সমস্যা হয়েছে, কিছুক্ষণ পর আবার চেষ্টা করুন।")
        except Exception:
            pass


async def anymsg(c, m):
    print("MESSAGE ESECHE:", m.text, flush=True)


async def sweeper():
    while True:
        try:
            now = ts(datetime.now(timezone.utc))
            for d in await get(f"/bot_deletes?delete_at=lt.{now}&select=id,chat_id,message_id"):
                try:
                    await app.delete_messages(d["chat_id"], d["message_id"])
                except Exception as e:
                    print(e)
                async with aiohttp.ClientSession() as s:
                    await s.delete(SB + f"/bot_deletes?id=eq.{d['id']}", headers=H)
        except Exception as e:
            print(e)
        await asyncio.sleep(60)


async def notify():
    while True:
        try:
            for u in await get("/profiles?notified=eq.false&select=id,email,tg_username"):
                await app.send_message(
                    ADMIN,
                    f"🆕 নতুন ইউজার: {u['email']} @{u['tg_username']}",
                    parse_mode=enums.ParseMode.DISABLED,  # ইউজারের লেখা যেন ফরম্যাট/লিংক হয়ে না যায়
                )
                async with aiohttp.ClientSession() as s:
                    await s.patch(SB + f"/profiles?id=eq.{u['id']}", headers=H, json={"notified": True})
        except Exception as e:
            print(e)
        await asyncio.sleep(30)


async def main():
    global app
    app = Client(
        "bot",
        api_id=int(E["API_ID"]),
        api_hash=E["API_HASH"],
        bot_token=E["BOT_TOKEN"],
        in_memory=True,
    )
    app.add_handler(MessageHandler(start, filters.command("start") & filters.private), group=0)
    app.add_handler(MessageHandler(link, filters.command("link") & filters.private), group=0)
    app.add_handler(MessageHandler(anymsg, filters.private), group=1)
    await app.start()
    me = await app.get_me()
    print("BOT CHALU:", me.username, flush=True)

    await resolve_channel()

    asyncio.create_task(notify())
    asyncio.create_task(sweeper())
    w = web.Application()
    w.router.add_get("/", lambda r: web.Response(text="ok"))
    rn = web.AppRunner(w)
    await rn.setup()
    await web.TCPSite(rn, "0.0.0.0", int(E.get("PORT", 10000))).start()
    await asyncio.Event().wait()


asyncio.run(main())
