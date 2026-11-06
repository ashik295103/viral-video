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
COOLDOWN = 8  # একই ইউজার কত সেকেন্ডে একবার রিকোয়েস্ট দিতে পারবে
LAST = {}
app = None
SES = None


def ses():
    """একটাই HTTP সেশন বারবার ব্যবহার হয় (প্রতিবার নতুন সংযোগ খুলতে সময় লাগত)।"""
    global SES
    if SES is None or SES.closed:
        SES = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return SES


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
    async with ses().get(SB + path, headers=H) as r:
        return await r.json()


async def schedule(chat, *ids):
    t = ts(datetime.now(timezone.utc) + timedelta(hours=HOURS))
    await ses().post(
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
    async with ses().post(url, json=payload) as r:
        data = await r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "copyMessage failed"))
    return data["result"]["message_id"]


TOKEN_MIN = 10  # ওয়েবসাইট থেকে পাওয়া লিংক কত মিনিট কাজ করবে


async def consume_token(tok):
    """টোকেন একবারই ব্যবহার করা যায়: মুছে ফেলার সাথে সাথে msg_id ফেরত আসে।"""
    cut = ts(datetime.now(timezone.utc) - timedelta(minutes=TOKEN_MIN))
    hdr = {**H, "Prefer": "return=representation"}
    async with ses().delete(
        SB + f"/dl_tokens?token=eq.{quote(tok, safe='')}&created_at=gt.{cut}", headers=hdr
    ) as r:
        rows = await r.json()
    return int(rows[0]["msg_id"]) if isinstance(rows, list) and rows else None


async def start(c, m):
    try:
        payload = m.command[1] if len(m.command) > 1 else ""
        if not payload:
            return await m.reply("🔥 Viral Video বটে স্বাগতম! ওয়েবসাইট থেকে ভিডিও লিংকে ক্লিক করুন।")
        uid = m.from_user.id
        is_admin = uid == ADMIN
        if not is_admin and too_fast(uid):
            return await m.reply("⏳ একটু অপেক্ষা করুন, কয়েক সেকেন্ড পর আবার চেষ্টা করুন।")

        mid = None
        if payload.startswith("t_"):
            tok = payload[2:]
            if not tok.isalnum() or len(tok) > 64:
                return await m.reply("❌ লিংকটি ঠিক নয়। ওয়েবসাইট থেকে আবার চেষ্টা করুন।")
            st, mid = await asyncio.gather(
                get("/settings?id=eq.1&select=maintenance"),
                consume_token(tok),
            )
            if isinstance(st, list) and st and st[0].get("maintenance") and not is_admin:
                return await m.reply("🛠️ রক্ষণাবেক্ষণের কাজ চলছে। খুব দ্রুত সমাধান করা হবে। সাময়িক সময়ের জন্য আমরা দুঃখিত।")
            if mid is None:
                return await m.reply("⌛ এই লিংকের মেয়াদ শেষ অথবা আগেই ব্যবহার হয়ে গেছে। ওয়েবসাইট থেকে ভিডিওটি আবার খুলুন।")
        elif payload.startswith("video_") and is_admin:
            try:
                mid = int(payload[6:])
            except ValueError:
                return await m.reply("❌ ভিডিও পাওয়া যায়নি।")
        else:
            return await m.reply("🔗 ভিডিও দেখতে ওয়েবসাইটে গিয়ে ভিডিওর Watch/Download বাটনে চাপুন।")

        vid = await copy_via_api(m.chat.id, mid)
        n = await m.reply(f"⏳ এই ভিডিও {HOURS} ঘণ্টা পর অটো ডিলিট হয়ে যাবে। আবার দেখতে হলে ওয়েবসাইট থেকে আসুন।")
        await schedule(m.chat.id, vid, n.id, m.id)
    except Exception as e:
        print("START ERROR:", repr(e), flush=True)
        try:
            await m.reply("⚠️ একটু সমস্যা হয়েছে, কিছুক্ষণ পর আবার চেষ্টা করুন।")  # ভেতরের এরর ইউজারকে দেখানো হয় না
        except Exception as e2:
            print("REPLY ERROR:", repr(e2), flush=True)


async def sweeper():
    while True:
        try:
            now = ts(datetime.now(timezone.utc))
            old_cut = ts(datetime.now(timezone.utc) - timedelta(minutes=30))
            await ses().delete(SB + f"/dl_tokens?created_at=lt.{old_cut}", headers=H)
            rows = await get(f"/bot_deletes?delete_at=lt.{now}&select=id,chat_id,message_id")
            if isinstance(rows, list):
                for d in rows:
                    try:
                        await app.delete_messages(d["chat_id"], d["message_id"])
                    except Exception as e:
                        print(e)
                    await ses().delete(SB + f"/bot_deletes?id=eq.{d['id']}", headers=H)
        except Exception as e:
            print(e)
        await asyncio.sleep(60)


async def notify():
    while True:
        try:
            rows = await get("/profiles?notified=eq.false&select=id,email,tg_username")
            if isinstance(rows, list):
                for u in rows:
                    try:  # একজনের ক্ষেত্রে সমস্যা হলে বাকিরা আটকে যাবে না
                        await app.send_message(
                            ADMIN,
                            f"🆕 নতুন ইউজার: {u['email']} @{u['tg_username']}",
                            parse_mode=enums.ParseMode.DISABLED,  # ইউজারের লেখা যেন ফরম্যাট/লিংক হয়ে না যায়
                        )
                        await ses().patch(SB + f"/profiles?id=eq.{u['id']}", headers=H, json={"notified": True})
                    except Exception as e:
                        print("NOTIFY ERROR:", repr(e), flush=True)
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
