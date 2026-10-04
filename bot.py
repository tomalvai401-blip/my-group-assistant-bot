import os
import re
import time
import sqlite3
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
from openai import AsyncOpenAI

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip()

PRAYER_COUNTRY = os.getenv(
    "PRAYER_COUNTRY",
    "Bangladesh"
).strip()

PRAYER_CITY = os.getenv(
    "PRAYER_CITY",
    "Narsingdi"
).strip()

TZ = ZoneInfo("Asia/Dhaka")

OPENAI_MODEL = "gpt-5.5"

DB_FILE = "bot.db"


if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN পাওয়া যায়নি।")

if not OPENAI_API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY পাওয়া যায়নি।")


try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except Exception:
    ADMIN_ID = 0


client = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            title TEXT,
            username TEXT,
            created_at TEXT,
            last_seen TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            media_type TEXT NOT NULL,
            file_id TEXT NOT NULL,
            category TEXT DEFAULT 'other',
            added_by INTEGER,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


def now_str():
    return datetime.now(TZ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def db_execute(
    query,
    params=(),
    fetch=False,
    fetchone=False
):

    conn = db_connect()
    cur = conn.cursor()

    cur.execute(
        query,
        params
    )

    result = None

    if fetch:
        result = cur.fetchall()

    if fetchone:
        result = cur.fetchone()

    conn.commit()
    conn.close()

    return result


# =========================================================
# USERS / CHATS
# =========================================================

def save_user(user):

    if not user:
        return

    db_execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            last_name,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        user.last_name or "",
        now_str()
    ))


def save_chat(chat):

    if not chat:
        return

    db_execute("""
        INSERT INTO chats (
            chat_id,
            chat_type,
            title,
            username,
            created_at,
            last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            title=excluded.title,
            username=excluded.username,
            last_seen=excluded.last_seen
    """, (
        chat.id,
        chat.type,
        chat.title or "",
        chat.username or "",
        now_str(),
        now_str()
    ))


def save_message(
    chat_id,
    user_id,
    role,
    content
):

    if not content:
        return

    db_execute("""
        INSERT INTO messages (
            chat_id,
            user_id,
            role,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        chat_id,
        user_id,
        role,
        content[:8000],
        now_str()
    ))


def get_history(
    chat_id,
    limit=10
):

    rows = db_execute("""
        SELECT role, content
        FROM messages
        WHERE chat_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (
        chat_id,
        limit
    ), fetch=True)

    rows = list(reversed(rows))

    return [
        {
            "role": row["role"],
            "content": row["content"]
        }
        for row in rows
        if row["role"] in (
            "user",
            "assistant"
        )
    ]


# =========================================================
# STATE
# =========================================================

def set_state(
    key,
    value
):

    db_execute("""
        INSERT INTO bot_state (
            key,
            value
        )
        VALUES (?, ?)

        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (
        key,
        str(value)
    ))


def get_state(
    key,
    default=None
):

    row = db_execute("""
        SELECT value
        FROM bot_state
        WHERE key=?
    """, (
        key,
    ), fetchone=True)

    if row:
        return row["value"]

    return default


# =========================================================
# ADMIN
# =========================================================

def is_admin(user_id):

    return (
        ADMIN_ID != 0
        and user_id == ADMIN_ID
    )


async def admin_only(update):

    user = update.effective_user

    if not user or not is_admin(user.id):

        await update.effective_message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return False

    return True


# =========================================================
# RATE LIMIT
# =========================================================

rate_data = {}


def check_rate_limit(user_id):

    now = time.time()

    values = rate_data.setdefault(
        user_id,
        []
    )

    values[:] = [
        t for t in values
        if now - t < 5
    ]

    if len(values) >= 7:
        return False

    values.append(now)

    return True


# =========================================================
# TEXT
# =========================================================

def normalize_text(text):

    text = text.lower().strip()

    text = re.sub(
        r"[^\w\u0980-\u09ff\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# =========================================================
# FIXED REPLIES
# =========================================================

def fixed_reply(text):

    t = normalize_text(text)

    # Greeting
    if t in {
        "হাই",
        "হ্যালো",
        "হাই হাই",
        "hi",
        "hello",
        "hey"
    }:

        return (
            "হাই! 👋 "
            "কেমন আছেন? কীভাবে সাহায্য করতে পারি?"
        )

    # Salam
    if t in {
        "আসসালামু আলাইকুম",
        "assalamualaikum",
        "assalamu alaikum"
    }:

        return (
            "ওয়ালাইকুম আসসালাম! 🤝 "
            "কেমন আছেন?"
        )

    # How are you
    if t in {
        "কেমন আছো",
        "কেমন আছেন",
        "কেমন আছ",
        "how are you",
        "how r u"
    }:

        return (
            "আমি ভালো আছি! 😊 "
            "আপনি কেমন আছেন?"
        )

    # Thanks
    if t in {
        "ধন্যবাদ",
        "অনেক ধন্যবাদ",
        "thanks",
        "thank you",
        "থ্যাংকস"
    }:

        return (
            "স্বাগতম! 😊 "
            "যখন দরকার হবে বলবেন।"
        )

    # Bye
    if t in {
        "বাই",
        "বিদায়",
        "bye",
        "goodbye"
    }:

        return (
            "ঠিক আছে! 👋 "
            "ভালো থাকবেন।"
        )

    # Electricity
    electricity = [
        "বিদ্যুৎ নাই",
        "বিদ্যুৎ নেই",
        "কারেন্ট নাই",
        "কারেন্ট নেই",
        "লাইট নাই",
        "লাইট নেই"
    ]

    if any(x in t for x in electricity):

        return (
            "বিদ্যুৎ না থাকার কারণ হতে পারে "
            "লোডশেডিং, লাইনে ত্রুটি, সাবস্টেশনের সমস্যা "
            "অথবা রক্ষণাবেক্ষণ। নির্দিষ্ট কারণ জানতে "
            "আপনার এলাকার বিদ্যুৎ অফিসের আপডেট দেখা সবচেয়ে নির্ভরযোগ্য।"
        )

    # Internet
    internet = [
        "ইন্টারনেট নাই",
        "ইন্টারনেট নেই",
        "নেট নাই",
        "নেট নেই",
        "wifi নাই",
        "wifi নেই",
        "ওয়াইফাই নাই",
        "ওয়াইফাই নেই"
    ]

    if any(x in t for x in internet):

        return (
            "ইন্টারনেট না থাকার কারণ হতে পারে "
            "ISP-এর সমস্যা, রাউটার/মোবাইল ডাটার সমস্যা, "
            "নেটওয়ার্ক congestion অথবা maintenance। "
            "আগে Wi-Fi/Data বন্ধ করে আবার চালু করে "
            "অন্য একটি website বা app খুলে পরীক্ষা করুন।"
        )

    return None


# =========================================================
# CONTENT
# =========================================================

CONTENT_WORDS = [
    "গান",
    "song",
    "নাটক",
    "drama",
    "মুভি",
    "movie",
    "সিনেমা",
    "ভিডিও",
    "video",
    "ডান্স",
    "dance",
    "ছবি",
    "photo",
    "picture"
]


REQUEST_WORDS = [
    "দাও",
    "দেন",
    "দিবে",
    "চাই",
    "লাগবে",
    "পাঠাও",
    "পাঠান",
    "send",
    "give",
    "want",
    "please",
    "দেখাও",
    "দেখতে চাই"
]


def is_content_request(text):

    t = normalize_text(text)

    return (
        any(x in t for x in CONTENT_WORDS)
        and
        any(x in t for x in REQUEST_WORDS)
    )


def extract_content_query(text):

    t = normalize_text(text)

    remove_words = (
        CONTENT_WORDS
        + REQUEST_WORDS
        + [
            "আমাকে",
            "একটা",
            "একটি",
            "আমার",
            "প্লিজ",
            "please",
            "টা",
            "টি",
            "টাও"
        ]
    )

    for word in remove_words:

        t = re.sub(
            r"\b" + re.escape(word) + r"\b",
            " ",
            t
        )

    return re.sub(
        r"\s+",
        " ",
        t
    ).strip()


def search_content(query):

    query = normalize_text(query)

    if not query:
        return None

    row = db_execute("""
        SELECT *
        FROM contents
        WHERE lower(title) LIKE ?
        ORDER BY id DESC
        LIMIT 1
    """, (
        f"%{query}%",
    ), fetchone=True)

    if row:
        return row

    words = [
        x for x in query.split()
        if len(x) >= 2
    ]

    if not words:
        return None

    conditions = []
    params = []

    for word in words[:6]:

        conditions.append(
            "lower(title) LIKE ?"
        )

        params.append(
            f"%{word}%"
        )

    return db_execute(
        f"""
        SELECT *
        FROM contents
        WHERE {" OR ".join(conditions)}
        ORDER BY id DESC
        LIMIT 1
        """,
        tuple(params),
        fetchone=True
    )


async def send_saved_content(
    update,
    row
):

    message = update.effective_message

    try:

        await message.reply_text(
            f"🎬 {row['title']}\n\n"
            "⏳ পাঠানো হচ্ছে..."
        )

        media_type = row["media_type"]
        file_id = row["file_id"]

        if media_type == "video":

            await message.reply_video(
                video=file_id,
                supports_streaming=True
            )

        elif media_type == "audio":

            await message.reply_audio(
                audio=file_id
            )

        elif media_type == "photo":

            await message.reply_photo(
                photo=file_id
            )

        elif media_type == "animation":

            await message.reply_animation(
                animation=file_id
            )

        else:

            await message.reply_document(
                document=file_id
            )

        await message.reply_text(
            "আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝"
        )

        return True

    except Exception as e:

        print(
            "CONTENT ERROR:",
            repr(e)
        )

        await message.reply_text(
            "❌ Content পাঠাতে সমস্যা হয়েছে।"
        )

        return False


# =========================================================
# PENDING CONTENT
# =========================================================

pending_content = {}


def set_pending(
    chat_id,
    user_id
):

    pending_content[chat_id] = {
        "user_id": user_id,
        "time": time.time()
    }


def pending_exists(
    chat_id,
    user_id
):

    data = pending_content.get(
        chat_id
    )

    if not data:
        return False

    if data["user_id"] != user_id:
        return False

    if time.time() - data["time"] > 600:

        pending_content.pop(
            chat_id,
            None
        )

        return False

    return True


def clear_pending(chat_id):

    pending_content.pop(
        chat_id,
        None
    )


# =========================================================
# OPENAI
# =========================================================

SYSTEM_PROMPT = """
তুমি একটি Telegram group assistant।

ব্যবহারকারীর প্রশ্নের সরাসরি উত্তর দেবে।

অকারণে এসব বলবে না:
- আচ্ছা
- ঠিক আছে
- আরও একটু বলুন
- আমি শুনছি

ব্যবহারকারী বাংলা লিখলে বাংলায় উত্তর দেবে।
Banglish হলে সহজ Banglish/বাংলা ব্যবহার করবে।
English হলে English-এ উত্তর দিতে পারবে।

প্রশ্ন বুঝতে না পারলে প্রয়োজনীয় clarification করবে।

নিজের কাছে কোনো file, video বা media আছে বলে মিথ্যা বলবে না।

Telegram-এর saved content system আলাদাভাবে program handle করে।
তাই গান, নাটক, movie, video বা photo-এর saved content নিজে থেকে বানিয়ে দেওয়ার দাবি করবে না।

সঠিক তথ্য না জানলে নিশ্চিতভাবে ভুল তথ্য দেবে না।

উত্তর সংক্ষিপ্ত, স্বাভাবিক ও helpful রাখবে।
"""


async def ai_reply(
    chat_id,
    user_text
):

    history = get_history(
        chat_id,
        10
    )

    messages = []

    for item in history:

        messages.append({
            "role": item["role"],
            "content": item["content"]
        })

    # বর্তমান user message নিশ্চিত করা
    if not messages or not (
        messages[-1]["role"] == "user"
        and
        messages[-1]["content"] == user_text
    ):

        messages.append({
            "role": "user",
            "content": user_text
        })

    try:

        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT,
            input=messages,
            max_output_tokens=500
        )

        answer = getattr(
            response,
            "output_text",
            ""
        )

        if not answer:

            return (
                "দুঃখিত, এখন উত্তর তৈরি করতে পারছি না।"
            )

        return answer.strip()

    except Exception as e:

        print(
            "OPENAI ERROR:",
            repr(e)
        )

        return (
            "😔 এই মুহূর্তে AI response দিতে সমস্যা হচ্ছে। "
            "একটু পরে আবার চেষ্টা করুন।"
        )


# =========================================================
# WEATHER
# =========================================================

async def get_weather():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=24.1344"
        "&longitude=90.7860"
        "&current=temperature_2m,"
        "relative_humidity_2m,"
        "weather_code,"
        "wind_speed_10m"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=10
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return None

                data = await response.json()

        current = data.get(
            "current",
            {}
        )

        return (
            f"🌤️ {PRAYER_CITY} Weather\n\n"
            f"{weather_description(current.get('weather_code', 0))}\n"
            f"🌡️ তাপমাত্রা: {current.get('temperature_2m', '?')}°C\n"
            f"💧 আর্দ্রতা: {current.get('relative_humidity_2m', '?')}%\n"
            f"💨 বাতাস: {current.get('wind_speed_10m', '?')} km/h"
        )

    except Exception as e:

        print(
            "WEATHER ERROR:",
            repr(e)
        )

        return None


def weather_description(code):

    code = int(code or 0)

    if code == 0:
        return "☀️ পরিষ্কার"

    if code in (1, 2, 3):
        return "⛅ আংশিক মেঘলা"

    if code in (45, 48):
        return "🌫️ কুয়াশা"

    if code in (51, 53, 55, 56, 57):
        return "🌦️ গুঁড়ি গুঁড়ি বৃষ্টি"

    if code in (61, 63, 65, 66, 67):
        return "🌧️ বৃষ্টি"

    if code in (80, 81, 82):
        return "🌧️ বৃষ্টির ঝাপটা"

    if code in (95, 96, 99):
        return "⛈️ বজ্রসহ বৃষ্টি"

    return "🌤️ আবহাওয়া পরিবর্তনশীল"


# =========================================================
# PRAYER
# =========================================================

async def get_prayer_times():

    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        "&method=1"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=10
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return None

                data = await response.json()

        timings = data[
            "data"
        ][
            "timings"
        ]

        return (
            f"🕌 {PRAYER_CITY} নামাজের সময়\n\n"
            f"🌅 ফজর: {timings.get('Fajr', '-')}\n"
            f"☀️ সূর্যোদয়: {timings.get('Sunrise', '-')}\n"
            f"🕛 যোহর: {timings.get('Dhuhr', '-')}\n"
            f"🌇 আসর: {timings.get('Asr', '-')}\n"
            f"🌆 মাগরিব: {timings.get('Maghrib', '-')}\n"
            f"🌙 এশা: {timings.get('Isha', '-')}"
        )

    except Exception as e:

        print(
            "PRAYER ERROR:",
            repr(e)
        )

        return None


# =========================================================
# ADMIN COMMANDS
# =========================================================

async def start_command(
    update,
    context
):

    await update.effective_message.reply_text(
        "👋 Welcome!\n\n"
        "আমি আপনার Telegram AI Assistant।\n"
        "বাংলা, Banglish অথবা English-এ কথা বলতে পারেন।"
    )


async def admin_command(
    update,
    context
):

    if not await admin_only(update):
        return

    await update.effective_message.reply_text(
        "👑 Admin Panel\n\n"
        "/addsong - Content যোগ করুন\n"
        "/list - Saved content\n"
        "/stats - Statistics\n"
        "/delete ID - Content delete\n"
        "/broadcast TEXT - Broadcast\n"
        "/admintest - Admin test"
    )


async def admintest_command(
    update,
    context
):

    if not await admin_only(update):
        return

    await update.effective_message.reply_text(
        "✅ Admin verification successful."
    )


async def addsong_command(
    update,
    context
):

    if not await admin_only(update):
        return

    context.user_data[
        "waiting_media"
    ] = True

    context.user_data.pop(
        "pending_media",
        None
    )

    await update.effective_message.reply_text(
        "📥 এখন Video / Audio / Photo / Document পাঠান।\n\n"
        "Media পাওয়ার পর আমি Title চাইব।"
    )


async def list_command(
    update,
    context
):

    if not await admin_only(update):
        return

    rows = db_execute("""
        SELECT id, title, media_type, category
        FROM contents
        ORDER BY id DESC
        LIMIT 50
    """, fetch=True)

    if not rows:

        await update.effective_message.reply_text(
            "📭 এখনো কোনো saved content নেই।"
        )

        return

    lines = [
        "📚 Saved Content\n"
    ]

    for row in rows:

        lines.append(
            f"ID: {row['id']}\n"
            f"🎬 {row['title']}\n"
            f"📁 {row['media_type']}\n"
            f"🏷️ {row['category']}\n"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000]
    )


async def stats_command(
    update,
    context
):

    if not await admin_only(update):
        return

    users = db_execute(
        "SELECT COUNT(*) c FROM users",
        fetchone=True
    )["c"]

    chats = db_execute(
        "SELECT COUNT(*) c FROM chats",
        fetchone=True
    )["c"]

    contents = db_execute(
        "SELECT COUNT(*) c FROM contents",
        fetchone=True
    )["c"]

    messages = db_execute(
        "SELECT COUNT(*) c FROM messages",
        fetchone=True
    )["c"]

    await update.effective_message.reply_text(
        "📊 Bot Statistics\n\n"
        f"👤 Users: {users}\n"
        f"💬 Chats: {chats}\n"
        f"🎬 Contents: {contents}\n"
        f"💭 Messages: {messages}"
    )


async def delete_command(
    update,
    context
):

    if not await admin_only(update):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "ব্যবহার করুন:\n/delete ID"
        )

        return

    try:
        content_id = int(
            context.args[0]
        )

    except ValueError:

        await update.effective_message.reply_text(
            "❌ ID number হতে হবে।"
        )

        return

    row = db_execute(
        "SELECT title FROM contents WHERE id=?",
        (content_id,),
        fetchone=True
    )

    if not row:

        await update.effective_message.reply_text(
            "❌ এই ID পাওয়া যায়নি।"
        )

        return

    db_execute(
        "DELETE FROM contents WHERE id=?",
        (content_id,)
    )

    await update.effective_message.reply_text(
        f"✅ Deleted:\n{row['title']}"
    )


async def broadcast_command(
    update,
    context
):

    if not await admin_only(update):
        return

    text = " ".join(
        context.args
    ).strip()

    if not text:

        await update.effective_message.reply_text(
            "ব্যবহার করুন:\n/broadcast আপনার message"
        )

        return

    rows = db_execute(
        "SELECT chat_id FROM chats",
        fetch=True
    )

    success = 0
    failed = 0

    for row in rows:

        try:

            await context.bot.send_message(
                chat_id=row["chat_id"],
                text=text
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except Exception as e:

            print(
                "BROADCAST ERROR:",
                repr(e)
            )

            failed += 1

    await update.effective_message.reply_text(
        "📢 Broadcast শেষ।\n\n"
        f"✅ Sent: {success}\n"
        f"❌ Failed: {failed}"
    )


async def weather_command(
    update,
    context
):

    result = await get_weather()

    await update.effective_message.reply_text(
        result or
        "❌ Weather data পাওয়া যাচ্ছে না।"
    )


async def prayer_command(
    update,
    context
):

    result = await get_prayer_times()

    await update.effective_message.reply_text(
        result or
        "❌ নামাজের সময় পাওয়া যাচ্ছে না।"
    )


# =========================================================
# ADMIN MEDIA
# =========================================================

async def handle_admin_media(
    update,
    context
):

    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return False

    if not context.user_data.get(
        "waiting_media"
    ):
        return False

    media_type = None
    file_id = None

    if message.video:

        media_type = "video"
        file_id = message.video.file_id

    elif message.audio:

        media_type = "audio"
        file_id = message.audio.file_id

    elif message.photo:

        media_type = "photo"
        file_id = message.photo[-1].file_id

    elif message.document:

        media_type = "document"
        file_id = message.document.file_id

    elif message.animation:

        media_type = "animation"
        file_id = message.animation.file_id

    if not file_id:
        return False

    context.user_data[
        "pending_media"
    ] = {
        "media_type": media_type,
        "file_id": file_id
    }

    context.user_data[
        "waiting_media"
    ] = False

    context.user_data[
        "waiting_title"
    ] = True

    await message.reply_text(
        "✅ Media পেয়েছি।\n\n"
        "এখন Content-এর Title লিখুন।"
    )

    return True


async def handle_admin_title(
    update,
    context
):

    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return False

    if not context.user_data.get(
        "waiting_title"
    ):
        return False

    title = message.text.strip()

    if not title:

        await message.reply_text(
            "❌ Title খালি রাখা যাবে না।"
        )

        return True

    pending = context.user_data.get(
        "pending_media"
    )

    if not pending:

        context.user_data[
            "waiting_title"
        ] = False

        return False

    category = detect_category(
        title
    )

    db_execute("""
        INSERT INTO contents (
            title,
            media_type,
            file_id,
            category,
            added_by,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        title,
        pending["media_type"],
        pending["file_id"],
        category,
        user.id,
        now_str()
    ))

    context.user_data.pop(
        "pending_media",
        None
    )

    context.user_data[
        "waiting_title"
    ] = False

    await message.reply_text(
        "✅ Content সফলভাবে Saved হয়েছে!\n\n"
        f"🎬 Title: {title}\n"
        f"📁 Type: {pending['media_type']}\n"
        f"🏷️ Category: {category}"
    )

    return True


def detect_category(title):

    t = normalize_text(
        title
    )

    if "গান" in t or "song" in t:
        return "song"

    if "নাটক" in t or "drama" in t:
        return "drama"

    if (
        "মুভি" in t
        or "movie" in t
        or "সিনেমা" in t
    ):
        return "movie"

    if "ডান্স" in t or "dance" in t:
        return "dance"

    if "ভিডিও" in t or "video" in t:
        return "video"

    if "ছবি" in t or "photo" in t:
        return "photo"

    return "other"


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(
    update,
    context
):

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    save_user(user)
    save_chat(chat)

    # Admin media
    if await handle_admin_media(
        update,
        context
    ):
        return

    # Text only
    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # Admin title
    if await handle_admin_title(
        update,
        context
    ):
        return

    # Rate limit
    if not check_rate_limit(
        user.id
    ):

        await message.reply_text(
            "⏳ একটু ধীরে বলুন, আমি শুনছি। 🙂"
        )

        return

    # -----------------------------------------------------
    # Content request
    # -----------------------------------------------------

    if is_content_request(text):

        await message.reply_text(
            "👋 Welcome!\n"
            "⏳ একটু অপেক্ষা করুন, দিচ্ছি..."
        )

        query = extract_content_query(
            text
        )

        row = search_content(
            query
        )

        if row:

            await send_saved_content(
                update,
                row
            )

            return

        set_pending(
            chat.id,
            user.id
        )

        await message.reply_text(
            "❌ এই নামে কোনো saved content পাওয়া যায়নি।\n\n"
            "📝 যে content চান তার নামটি লিখুন।"
        )

        return

    # -----------------------------------------------------
    # Pending content
    # -----------------------------------------------------

    if pending_exists(
        chat.id,
        user.id
    ):

        row = search_content(
            text
        )

        if row:

            clear_pending(
                chat.id
            )

            await send_saved_content(
                update,
                row
            )

            return

        await message.reply_text(
            "❌ এই নামে কোনো saved content পাওয়া যায়নি।\n"
            "আবার নামটি লিখুন।"
        )

        return

    # -----------------------------------------------------
    # Fixed replies
    # -----------------------------------------------------

    reply = fixed_reply(
        text
    )

    if reply:

        save_message(
            chat.id,
            user.id,
            "user",
            text
        )

        save_message(
            chat.id,
            0,
            "assistant",
            reply
        )

        await message.reply_text(
            reply
        )

        return

    # -----------------------------------------------------
    # Weather
    # -----------------------------------------------------

    normalized = normalize_text(
        text
    )

    weather_words = [
        "আবহাওয়া",
        "weather",
        "বৃষ্টি হবে",
        "আজ বৃষ্টি",
        "বৃষ্টি আসবে",
        "তাপমাত্রা",
        "temperature"
    ]

    if any(
        x in normalized
        for x in weather_words
    ):

        result = await get_weather()

        await message.reply_text(
            result or
            "❌ Weather data পাওয়া যাচ্ছে না।"
        )

        return

    # -----------------------------------------------------
    # Prayer
    # -----------------------------------------------------

    prayer_words = [
        "নামাজের সময়",
        "নামাজের ওয়াক্ত",
        "নামাজ কখন",
        "আজকের নামাজ",
        "prayer time"
    ]

    if any(
        x in normalized
        for x in prayer_words
    ):

        result = await get_prayer_times()

        await message.reply_text(
            result or
            "❌ নামাজের সময় পাওয়া যাচ্ছে না।"
        )

        return

    # -----------------------------------------------------
    # AI
    # -----------------------------------------------------

    save_message(
        chat.id,
        user.id,
        "user",
        text
    )

    answer = await ai_reply(
        chat.id,
        text
    )

    save_message(
        chat.id,
        0,
        "assistant",
        answer
    )

    await message.reply_text(
        answer
    )


# =========================================================
# HOURLY MESSAGES
# =========================================================

SPECIAL_MESSAGES = {

    0:
        "🌙 শুভ রাত্রি সবাইকে! 😴\n"
        "দিনের কাজ শেষ করে এখন একটু বিশ্রাম নিন।",

    7:
        "🌅 শুভ সকাল সবাইকে! ☀️\n"
        "নতুন দিনের শুরু হোক সুন্দরভাবে।\n"
        "সবার জন্য রইলো শুভকামনা। ❤️",

    8:
        "☀️ সকাল ৮টা!\n"
        "আজকের দিনটা ভালো কিছু দিয়ে শুরু হোক। 😊",

    9:
        "🌞 সকাল ৯টা!\n"
        "নিজের কাজগুলো সুন্দরভাবে এগিয়ে নিন। 💪",

    10:
        "☀️ সকাল ১০টা!\n"
        "ব্যস্ত দিনের মাঝেও একটু পানি পান করতে ভুলবেন না। 💧",

    12:
        "🌤️ শুভ দুপুর!\n"
        "দুপুরের খাবার খেয়ে একটু বিশ্রাম নিন। 😊",

    16:
        "🌇 বিকেল ৪টা!\n"
        "দিনের কাজ কেমন চলছে সবাই? 🙂",

    18:
        "🌆 শুভ সন্ধ্যা সবাইকে! ❤️\n"
        "দিনটা সুন্দরভাবে শেষ হোক।",

    19:
        "📚 Study Time!\n"
        "যারা পড়াশোনা করছেন, মনোযোগ দিয়ে পড়ুন। 💪📖",

    22:
        "🌙 রাত ১০টা!\n"
        "অনেক রাত হয়েছে—সময়মতো ঘুমানোর চেষ্টা করুন। 😴"
}


GENERIC_HOURS = {

    11: "🕐 এখন সময় ১১:০০ বাজে",
    13: "🕐 এখন সময় ১:০০ বাজে",
    14: "🕐 এখন সময় ২:০০ বাজে",
    15: "🕐 এখন সময় ৩:০০ বাজে",
    17: "🕐 এখন সময় ৫:০০ বাজে",
    20: "🕐 এখন সময় ৮:০০ বাজে",
    21: "🕐 এখন সময় ৯:০০ বাজে",
    23: "🕐 এখন সময় ১১:০০ বাজে"
}


async def hourly_loop(
    application
):

    while True:

        try:

            now = datetime.now(
                TZ
            )

            hour = now.hour
            minute = now.minute

            if minute <= 1:

                key = now.strftime(
                    "%Y-%m-%d-%H"
                )

                last = get_state(
                    "last_auto_hour"
                )

                if last != key:

                    text = (
                        SPECIAL_MESSAGES.get(hour)
                        or
                        GENERIC_HOURS.get(hour)
                    )

                    if text:

                        rows = db_execute(
                            "SELECT chat_id FROM chats",
                            fetch=True
                        )

                        for row in rows:

                            try:

                                await application.bot.send_message(
                                    chat_id=row["chat_id"],
                                    text=text
                                )

                                await asyncio.sleep(
                                    0.05
                                )

                            except Exception as e:

                                print(
                                    "AUTO ERROR:",
                                    repr(e)
                                )

                        set_state(
                            "last_auto_hour",
                            key
                        )

        except Exception as e:

            print(
                "HOURLY ERROR:",
                repr(e)
            )

        await asyncio.sleep(
            20
        )


# =========================================================
# STARTUP
# =========================================================

async def post_init(
    application
):

    init_db()

    application.create_task(
        hourly_loop(
            application
        )
    )

    print(
        "================================"
    )

    print(
        "BOT STARTED SUCCESSFULLY"
    )

    print(
        "TIMEZONE:",
        TZ
    )

    print(
        "MODEL:",
        OPENAI_MODEL
    )

    print(
        "================================"
    )


# =========================================================
# ERROR
# =========================================================

async def error_handler(
    update,
    context
):

    print(
        "TELEGRAM ERROR:",
        repr(context.error)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "admintest",
            admintest_command
        )
    )

    app.add_handler(
        CommandHandler(
            "addsong",
            addsong_command
        )
    )

    app.add_handler(
        CommandHandler(
            "list",
            list_command
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    app.add_handler(
        CommandHandler(
            "delete",
            delete_command
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_command
        )
    )

    app.add_handler(
        CommandHandler(
            "weather",
            weather_command
        )
    )

    app.add_handler(
        CommandHandler(
            "prayer",
            prayer_command
        )
    )

    # Normal messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # Media messages
    app.add_handler(
        MessageHandler(
            (
                filters.VIDEO
                | filters.AUDIO
                | filters.PHOTO
                | filters.Document.ALL
                | filters.ANIMATION
            ),
            handle_message
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "Starting Telegram bot..."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
