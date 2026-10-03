import os
import re
import json
import time
import sqlite3
import asyncio
import random
from datetime import datetime
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher

import aiohttp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").replace("@", "").strip()

PRAYER_CITY = os.getenv("PRAYER_CITY", "Narsingdi").strip()
PRAYER_COUNTRY = os.getenv("PRAYER_COUNTRY", "Bangladesh").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

TIMEZONE = ZoneInfo("Asia/Dhaka")
DB_FILE = "bot_database.db"

# Free-tier friendly model.
GEMINI_MODEL = "gemini-2.5-flash-lite"

# =========================================================
# CHECK CONFIG
# =========================================================

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN পাওয়া যায়নি। GitHub Secret চেক করুন।")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID পাওয়া যায়নি। GitHub Secret চেক করুন।")

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_seen TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    chat_type TEXT,
    title TEXT,
    last_seen TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS contents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    file_type TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT,
    created_at TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

db.commit()

db_lock = asyncio.Lock()

# =========================================================
# TIME
# =========================================================

def now():
    return datetime.now(TIMEZONE)


def bn(value):
    table = str.maketrans(
        "0123456789",
        "০১২৩৪৫৬৭৮৯"
    )
    return str(value).translate(table)


def time_text():
    n = now()
    return f"🕐 এখন সময় {bn(n.strftime('%I:%M'))} বাজে"


def hour_text(hour):
    if hour == 0:
        h = 12
    elif hour > 12:
        h = hour - 12
    else:
        h = hour

    return f"🕐 এখন সময় {bn(h)}:০০ বাজে"


# =========================================================
# ADMIN
# =========================================================

def is_admin(update: Update):
    if not update.effective_user:
        return False

    return update.effective_user.id == ADMIN_ID


async def admin_only(update: Update):
    if not is_admin(update):
        await update.effective_message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )
        return False

    return True


# =========================================================
# TRACK USERS / CHATS
# =========================================================

async def track_update(update: Update):

    if not update.effective_user:
        return

    user = update.effective_user

    username = user.username or ""
    first_name = user.first_name or ""

    chat = update.effective_chat

    async with db_lock:

        db.execute(
            """
            INSERT OR REPLACE INTO users
            (user_id, username, first_name, last_seen)
            VALUES (?, ?, ?, ?)
            """,
            (
                user.id,
                username,
                first_name,
                now().isoformat(),
            )
        )

        if chat:
            title = (
                chat.title
                or user.first_name
                or ""
            )

            db.execute(
                """
                INSERT OR REPLACE INTO chats
                (chat_id, chat_type, title, last_seen)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chat.id,
                    chat.type,
                    title,
                    now().isoformat(),
                )
            )

        db.commit()


# =========================================================
# TEXT NORMALIZE
# =========================================================

def normalize(text):

    text = text.lower().strip()

    replacements = {
        "গানটা": "গান",
        "গানটি": "গান",
        "ভিডিওটা": "ভিডিও",
        "ভিডিওটি": "ভিডিও",
        "ছবিটা": "ছবি",
        "ছবিটি": "ছবি",
        "den": "দেন",
        "dao": "দাও",
        "daw": "দাও",
        "de": "দাও",
        "vai": "ভাই",
        "bhai": "ভাই",
        "valo": "ভালো",
        "bhalo": "ভালো",
        "kemon": "কেমন",
        "achen": "আছেন",
        "acho": "আছো",
    }

    for a, b in replacements.items():
        text = text.replace(a, b)

    text = re.sub(
        r"[^\w\s\u0980-\u09ff]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


# =========================================================
# CONTENT CATEGORY
# =========================================================

def detect_category(title):

    t = normalize(title)

    if any(x in t for x in [
        "গান",
        "song",
        "music",
        "audio"
    ]):
        return "song"

    if any(x in t for x in [
        "নাটক",
        "drama",
        "natok"
    ]):
        return "drama"

    if any(x in t for x in [
        "মুভি",
        "movie",
        "film",
        "cinema"
    ]):
        return "movie"

    if any(x in t for x in [
        "নাচ",
        "dance"
    ]):
        return "dance"

    if any(x in t for x in [
        "ছবি",
        "photo",
        "picture",
        "wallpaper"
    ]):
        return "photo"

    if any(x in t for x in [
        "ভিডিও",
        "video"
    ]):
        return "video"

    return "other"


# =========================================================
# SAVE CONTENT
# =========================================================

async def save_content(
    file_id,
    file_type,
    title
):

    category = detect_category(title)

    async with db_lock:

        db.execute(
            """
            INSERT INTO contents
            (file_id, file_type, title, category, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_id,
                file_type,
                title,
                category,
                now().isoformat(),
            )
        )

        db.commit()


# =========================================================
# SEARCH CONTENT
# =========================================================

async def search_content(query):

    q = normalize(query)

    async with db_lock:

        rows = db.execute(
            """
            SELECT id, file_id, file_type,
                   title, category
            FROM contents
            ORDER BY id DESC
            """
        ).fetchall()

    if not rows:
        return None

    best = None
    best_score = 0

    for row in rows:

        content_id, file_id, file_type, title, category = row

        t = normalize(title)

        score = SequenceMatcher(
            None,
            q,
            t
        ).ratio()

        if q in t:
            score += 0.45

        q_words = set(q.split())
        t_words = set(t.split())

        if q_words and t_words:
            common = len(q_words & t_words)
            score += common * 0.08

        if score > best_score:
            best_score = score
            best = row

    if best_score >= 0.35:
        return best

    return None


# =========================================================
# SEND SAVED CONTENT
# =========================================================

async def send_saved_content(
    update,
    row
):

    content_id, file_id, file_type, title, category = row

    try:

        if file_type == "audio":

            await update.effective_message.reply_audio(
                audio=file_id,
                caption=f"🎵 {title}"
            )

        elif file_type == "video":

            await update.effective_message.reply_video(
                video=file_id,
                caption=f"🎬 {title}"
            )

        elif file_type == "photo":

            await update.effective_message.reply_photo(
                photo=file_id,
                caption=f"🖼️ {title}"
            )

        elif file_type == "voice":

            await update.effective_message.reply_voice(
                voice=file_id,
                caption=f"🎤 {title}"
            )

        elif file_type == "document":

            await update.effective_message.reply_document(
                document=file_id,
                caption=f"📁 {title}"
            )

        else:
            return False

        return True

    except Exception as e:

        print(
            "SEND CONTENT ERROR:",
            repr(e)
        )

        return False


# =========================================================
# MEDIA EXTRACTION
# =========================================================

def extract_media(message):

    if message.audio:
        return (
            message.audio.file_id,
            "audio"
        )

    if message.video:
        return (
            message.video.file_id,
            "video"
        )

    if message.photo:
        return (
            message.photo[-1].file_id,
            "photo"
        )

    if message.voice:
        return (
            message.voice.file_id,
            "voice"
        )

    if message.document:
        return (
            message.document.file_id,
            "document"
        )

    return None


# =========================================================
# AI - GEMINI
# =========================================================

AI_SYSTEM = """
তুমি একটি Telegram group assistant bot।

তোমার নাম নির্দিষ্ট করা নেই, তাই নিজেকে শুধু "Bot" বা
"সহকারী" হিসেবে পরিচয় দিতে পারো।

তুমি বাংলা, Banglish এবং English বুঝবে।

ব্যবহারকারীর ভাষার সাথে মিল রেখে উত্তর দেবে।

উত্তর:
- স্বাভাবিক
- বন্ধুসুলভ
- সংক্ষিপ্ত
- প্রয়োজন অনুযায়ী বিস্তারিত

ব্যবহারকারী সাধারণ কথা বললে সাধারণভাবে উত্তর দেবে।

গান, নাটক, মুভি, ভিডিও, ছবি বা অন্য কোনো saved media
চাইলে নিজে কোনো media link বানিয়ে দেবে না।
Media system আলাদাভাবে saved content খুঁজবে।

তুমি নিজের কাছে নেই এমন তথ্য নিশ্চিতভাবে জানো বলে দাবি করবে না।

ব্যবহারকারী কোনো ক্ষতিকর বা অনুপযুক্ত বিষয়ে সাহায্য চাইলে
নিরাপদভাবে প্রত্যাখ্যান করবে এবং নিরাপদ বিকল্প বলবে।
"""


async def gemini_reply(user_text):

    if not GEMINI_API_KEY:
        return None

    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_MODEL}:generateContent"
        f"?key={GEMINI_API_KEY}"
    )

    prompt = (
        AI_SYSTEM
        + "\n\nUser message:\n"
        + user_text
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 500
        }
    }

    try:

        timeout = aiohttp.ClientTimeout(
            total=25
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.post(
                url,
                json=payload
            ) as response:

                data = await response.json()

                if response.status != 200:

                    print(
                        "GEMINI ERROR:",
                        response.status,
                        data
                    )

                    return None

                candidates = data.get(
                    "candidates",
                    []
                )

                if not candidates:
                    return None

                parts = (
                    candidates[0]
                    .get("content", {})
                    .get("parts", [])
                )

                text_parts = []

                for part in parts:

                    if "text" in part:
                        text_parts.append(
                            part["text"]
                        )

                result = "\n".join(
                    text_parts
                ).strip()

                return result or None

    except Exception as e:

        print(
            "GEMINI EXCEPTION:",
            repr(e)
        )

        return None


# =========================================================
# RATE LIMIT
# =========================================================

rate_data = {}

def is_flooding(user_id):

    current = time.time()

    data = rate_data.setdefault(
        user_id,
        []
    )

    data[:] = [
        x for x in data
        if current - x < 5
    ]

    data.append(current)

    if len(data) > 7:
        return True

    return False


# =========================================================
# CONTENT REQUEST DETECTION
# =========================================================

CONTENT_WORDS = [
    "গান",
    "song",
    "music",
    "নাটক",
    "drama",
    "natok",
    "মুভি",
    "movie",
    "film",
    "ভিডিও",
    "video",
    "নাচ",
    "dance",
    "ছবি",
    "photo",
    "picture",
    "wallpaper",
]


def is_content_request(text):

    t = normalize(text)

    request_words = [
        "দাও",
        "দেন",
        "চাই",
        "লাগবে",
        "পাঠাও",
        "পাঠান",
        "দিবেন",
        "দিয়ে দাও",
        "send",
        "give",
        "dao",
        "den",
    ]

    has_content = any(
        word in t
        for word in CONTENT_WORDS
    )

    has_request = any(
        word in t
        for word in request_words
    )

    return has_content and has_request


# =========================================================
# PENDING REQUEST
# =========================================================

def set_pending(user_id, value):

    key = f"pending_{user_id}"

    db.execute(
        """
        INSERT OR REPLACE INTO bot_state
        (key, value)
        VALUES (?, ?)
        """,
        (
            key,
            json.dumps(value)
        )
    )

    db.commit()


def get_pending(user_id):

    key = f"pending_{user_id}"

    row = db.execute(
        """
        SELECT value
        FROM bot_state
        WHERE key = ?
        """,
        (key,)
    ).fetchone()

    if not row:
        return None

    try:
        return json.loads(row[0])
    except Exception:
        return None


def clear_pending(user_id):

    key = f"pending_{user_id}"

    db.execute(
        """
        DELETE FROM bot_state
        WHERE key = ?
        """,
        (key,)
    )

    db.commit()


# =========================================================
# ADMIN MEDIA SAVE
# =========================================================

async def handle_admin_media(
    update,
    context
):

    if not is_admin(update):
        return False

    media = extract_media(
        update.effective_message
    )

    if not media:
        return False

    file_id, file_type = media

    context.user_data[
        "admin_save"
    ] = {
        "file_id": file_id,
        "file_type": file_type
    }

    await update.effective_message.reply_text(
        "✅ Media পেয়েছি।\n\n"
        "এখন এই Content-এর নাম লিখুন।\n"
        "উদাহরণ: Amar Shonar Bangla গান"
    )

    return True


# =========================================================
# ADMIN TITLE SAVE
# =========================================================

async def handle_admin_title(
    update,
    context
):

    state = context.user_data.get(
        "admin_save"
    )

    if not state:
        return False

    title = (
        update.effective_message.text
        or ""
    ).strip()

    if not title:
        await update.effective_message.reply_text(
            "❌ Content-এর নাম লিখুন।"
        )
        return True

    await save_content(
        state["file_id"],
        state["file_type"],
        title
    )

    context.user_data.pop(
        "admin_save",
        None
    )

    await update.effective_message.reply_text(
        "✅ Content সফলভাবে Save হয়েছে।\n\n"
        f"📌 নাম: {title}"
    )

    return True


# =========================================================
# COMMANDS
# =========================================================

async def start(update, context):

    await track_update(update)

    await update.effective_message.reply_text(
        "👋 Welcome!\n\n"
        "আমি তোমাদের Group Assistant Bot।\n"
        "সাধারণভাবে কথা বললেও আমি উত্তর দেওয়ার চেষ্টা করব। 🤖"
    )


async def admin_test(update, context):

    if not await admin_only(update):
        return

    await update.effective_message.reply_text(
        "👑 Admin Test সফল!\n\n"
        f"Admin ID: {ADMIN_ID}\n"
        f"Username: @{ADMIN_USERNAME or 'Not Set'}"
    )


async def admin_help(update, context):

    if not await admin_only(update):
        return

    await update.effective_message.reply_text(
        "👑 ADMIN PANEL\n\n"
        "/addsong - Media save mode\n"
        "/list - Saved content list\n"
        "/delete ID - Content delete\n"
        "/stats - Bot statistics\n"
        "/broadcast TEXT - Broadcast\n"
        "/admintest - Admin test"
    )


async def addsong(update, context):

    if not await admin_only(update):
        return

    context.user_data[
        "waiting_admin_media"
    ] = True

    await update.effective_message.reply_text(
        "📥 এখন Media পাঠান।\n\n"
        "🎵 Audio\n"
        "🎬 Video\n"
        "🖼️ Photo\n"
        "🎤 Voice\n"
        "📁 Document\n\n"
        "Media পাওয়ার পর আমি নাম চাইব।"
    )


async def list_content(update, context):

    if not await admin_only(update):
        return

    rows = db.execute(
        """
        SELECT id, title, category
        FROM contents
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()

    if not rows:

        await update.effective_message.reply_text(
            "📭 কোনো Content Save করা নেই।"
        )
        return

    lines = [
        "📚 Saved Content:\n"
    ]

    for cid, title, category in rows:

        lines.append(
            f"🆔 {cid} | {title} | {category}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)
    )


async def delete_content(update, context):

    if not await admin_only(update):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "ব্যবহার করুন:\n"
            "/delete ID"
        )
        return

    try:
        cid = int(context.args[0])
    except ValueError:

        await update.effective_message.reply_text(
            "❌ ID সঠিক নয়।"
        )
        return

    row = db.execute(
        """
        SELECT title
        FROM contents
        WHERE id = ?
        """,
        (cid,)
    ).fetchone()

    if not row:

        await update.effective_message.reply_text(
            "❌ এই ID পাওয়া যায়নি।"
        )
        return

    db.execute(
        """
        DELETE FROM contents
        WHERE id = ?
        """,
        (cid,)
    )

    db.commit()

    await update.effective_message.reply_text(
        f"🗑️ Deleted: {row[0]}"
    )


async def stats(update, context):

    if not await admin_only(update):
        return

    users = db.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    chats = db.execute(
        "SELECT COUNT(*) FROM chats"
    ).fetchone()[0]

    contents = db.execute(
        "SELECT COUNT(*) FROM contents"
    ).fetchone()[0]

    await update.effective_message.reply_text(
        "📊 BOT STATS\n\n"
        f"👤 Users: {users}\n"
        f"👥 Chats: {chats}\n"
        f"📦 Content: {contents}"
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast(update, context):

    if not await admin_only(update):
        return

    text = " ".join(
        context.args
    ).strip()

    if not text:

        context.user_data[
            "broadcast_mode"
        ] = True

        await update.effective_message.reply_text(
            "📢 Broadcast mode ON.\n"
            "এখন যে Text পাঠাবেন সেটা সবাইকে যাবে।"
        )

        return

    await perform_broadcast(
        update,
        text
    )


async def perform_broadcast(
    update,
    text
):

    rows = db.execute(
        """
        SELECT chat_id
        FROM chats
        """
    ).fetchall()

    success = 0
    failed = 0

    for row in rows:

        chat_id = row[0]

        try:

            await update.get_bot().send_message(
                chat_id=chat_id,
                text=text
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except Exception as e:

            print(
                "Broadcast error:",
                chat_id,
                repr(e)
            )

            failed += 1

    await update.effective_message.reply_text(
        "📢 Broadcast শেষ।\n\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {failed}"
    )


# =========================================================
# WEATHER
# =========================================================

async def weather_text():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={24.1344}"
        f"&longitude={90.7860}"
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

                data = await response.json()

        current = data.get(
            "current",
            {}
        )

        temp = current.get(
            "temperature_2m",
            "?"
        )

        humidity = current.get(
            "relative_humidity_2m",
            "?"
        )

        wind = current.get(
            "wind_speed_10m",
            "?"
        )

        code = current.get(
            "weather_code",
            -1
        )

        weather_map = {
            0: "☀️ পরিষ্কার",
            1: "🌤️ হালকা মেঘ",
            2: "⛅ আংশিক মেঘলা",
            3: "☁️ মেঘলা",
            45: "🌫️ কুয়াশা",
            48: "🌫️ কুয়াশা",
            51: "🌦️ হালকা গুঁড়ি বৃষ্টি",
            53: "🌦️ গুঁড়ি বৃষ্টি",
            55: "🌧️ গুঁড়ি বৃষ্টি",
            61: "🌧️ হালকা বৃষ্টি",
            63: "🌧️ বৃষ্টি",
            65: "🌧️ ভারী বৃষ্টি",
            80: "🌦️ বৃষ্টির ঝরনা",
            81: "🌧️ বৃষ্টির ঝরনা",
            82: "⛈️ ভারী বৃষ্টির ঝরনা",
            95: "⛈️ বজ্রসহ বৃষ্টি",
        }

        condition = weather_map.get(
            code,
            "🌤️ পরিবর্তনশীল"
        )

        return (
            f"🌤️ {PRAYER_CITY} Weather\n\n"
            f"{condition}\n"
            f"🌡️ তাপমাত্রা: {temp}°C\n"
            f"💧 আর্দ্রতা: {humidity}%\n"
            f"💨 বাতাস: {wind} km/h"
        )

    except Exception:

        return (
            "❌ এখন Weather তথ্য পাওয়া যাচ্ছে না।"
        )


async def weather(update, context):

    await track_update(update)

    await update.effective_message.reply_text(
        await weather_text()
    )


# =========================================================
# PRAYER
# =========================================================

async def prayer(update, context):

    await track_update(update)

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

                data = await response.json()

        timings = (
            data
            .get("data", {})
            .get("timings", {})
        )

        await update.effective_message.reply_text(
            "🕌 আজকের নামাজের সময়\n\n"
            f"📍 {PRAYER_CITY}, {PRAYER_COUNTRY}\n\n"
            f"🌅 Fajr: {timings.get('Fajr', '-')}\n"
            f"☀️ Dhuhr: {timings.get('Dhuhr', '-')}\n"
            f"🌤️ Asr: {timings.get('Asr', '-')}\n"
            f"🌇 Maghrib: {timings.get('Maghrib', '-')}\n"
            f"🌙 Isha: {timings.get('Isha', '-')}"
        )

    except Exception:

        await update.effective_message.reply_text(
            "❌ Prayer time এখন পাওয়া যাচ্ছে না।"
        )


# =========================================================
# AUTOMATIC HOURLY MESSAGES
# =========================================================

SPECIAL_MESSAGES = {

    7: (
        "🌅 শুভ সকাল!\n\n"
        "নতুন দিনের শুরুটা হোক সুন্দর ও আনন্দময়। "
        "আজকের দিনটি ভালো কাটুক সবার। ❤️"
    ),

    8: (
        "☀️ সকাল ৮টা!\n\n"
        "দিনের কাজগুলো সুন্দরভাবে শুরু করুন। "
        "হাসিমুখে থাকুন। 😊"
    ),

    9: (
        "🌞 সকাল ৯টা!\n\n"
        "আজকের লক্ষ্যগুলো একে একে পূরণ করার চেষ্টা করুন। "
        "শুভকামনা রইলো। 💪"
    ),

    10: (
        "☕ সকাল ১০টা!\n\n"
        "কাজের মাঝে একটু বিরতি নিয়ে পানি পান করুন। 😊"
    ),

    12: (
        "🌤️ শুভ দুপুর!\n\n"
        "দুপুরটা শান্তিতে কাটুক। "
        "সময়মতো খাবার খেতে ভুলবেন না। 🍚"
    ),

    16: (
        "🌇 বিকেল ৪টা!\n\n"
        "দিনের বাকি সময়টুকুও সুন্দরভাবে কাটুক। 😊"
    ),

    18: (
        "🌆 শুভ সন্ধ্যা!\n\n"
        "সন্ধ্যার সময়টা পরিবারের মানুষদের সাথে সুন্দরভাবে কাটান। ❤️"
    ),

    19: (
        "📚 Study Time!\n\n"
        "পড়াশোনার জন্য কিছু সময় মনোযোগ দিন। "
        "ছোট ছোট নিয়মিত চেষ্টা বড় ফল এনে দেয়। 💪📖"
    ),

    22: (
        "🌙 রাত ১০টা!\n\n"
        "দিনের কাজ শেষ করে এখন ধীরে ধীরে বিশ্রামের প্রস্তুতি নিন। "
        "নিজের যত্ন নিন। 😴"
    ),

    0: (
        "🌙 শুভ রাত্রি!\n\n"
        "দিন শেষ। এখন ভালোভাবে বিশ্রাম নিন। "
        "আগামীকাল নতুন দিনের শুরু। 😴✨"
    ),
}


GENERIC_HOURS = {
    11,
    13,
    14,
    15,
    17,
    20,
    21,
    23,
}


def auto_message(hour):

    if hour in SPECIAL_MESSAGES:
        return SPECIAL_MESSAGES[hour]

    if hour in GENERIC_HOURS:
        return hour_text(hour)

    return None


async def get_state(key):

    async with db_lock:

        row = db.execute(
            """
            SELECT value
            FROM bot_state
            WHERE key = ?
            """,
            (key,)
        ).fetchone()

    return row[0] if row else None


async def set_state(key, value):

    async with db_lock:

        db.execute(
            """
            INSERT OR REPLACE INTO bot_state
            (key, value)
            VALUES (?, ?)
            """,
            (key, value)
        )

        db.commit()


async def automatic_loop(application):

    print("Automatic message loop started.")

    while True:

        try:

            current = now()

            hour = current.hour

            # Only check around the beginning of each hour.
            if current.minute <= 1:

                today_hour = (
                    current.strftime("%Y-%m-%d")
                    + f"-{hour}"
                )

                last_sent = await get_state(
                    "last_auto_hour"
                )

                if last_sent != today_hour:

                    message = auto_message(hour)

                    if message:

                        rows = db.execute(
                            """
                            SELECT chat_id
                            FROM chats
                            """
                        ).fetchall()

                        for row in rows:

                            chat_id = row[0]

                            try:

                                await application.bot.send_message(
                                    chat_id=chat_id,
                                    text=message
                                )

                                await asyncio.sleep(
                                    0.05
                                )

                            except Exception as e:

                                print(
                                    "AUTO SEND ERROR:",
                                    chat_id,
                                    repr(e)
                                )

                        await set_state(
                            "last_auto_hour",
                            today_hour
                        )

            await asyncio.sleep(20)

        except asyncio.CancelledError:
            raise

        except Exception as e:

            print(
                "AUTO LOOP ERROR:",
                repr(e)
            )

            await asyncio.sleep(20)


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(
    update,
    context
):

    if not update.effective_message:
        return

    await track_update(update)

    message = update.effective_message
    user = update.effective_user

    # -----------------------------------------------------
    # ADMIN DIRECT MEDIA
    # -----------------------------------------------------

    if is_admin(update):

        if context.user_data.get(
            "waiting_admin_media"
        ):

            media = extract_media(message)

            if media:

                file_id, file_type = media

                context.user_data.pop(
                    "waiting_admin_media",
                    None
                )

                context.user_data[
                    "admin_save"
                ] = {
                    "file_id": file_id,
                    "file_type": file_type
                }

                await message.reply_text(
                    "✅ Media পেয়েছি।\n"
                    "এখন Content-এর নাম লিখুন।"
                )

                return

        # Direct admin media save
        media = extract_media(message)

        if media and not message.text:

            file_id, file_type = media

            context.user_data[
                "admin_save"
            ] = {
                "file_id": file_id,
                "file_type": file_type
            }

            await message.reply_text(
                "✅ Media পেয়েছি।\n\n"
                "এখন Content-এর নাম লিখুন।"
            )

            return

        # Admin title
        if context.user_data.get(
            "admin_save"
        ):

            if message.text:

                handled = await handle_admin_title(
                    update,
                    context
                )

                if handled:
                    return

        # Broadcast mode
        if context.user_data.get(
            "broadcast_mode"
        ):

            if message.text:

                context.user_data.pop(
                    "broadcast_mode",
                    None
                )

                await perform_broadcast(
                    update,
                    message.text
                )

                return

    # -----------------------------------------------------
    # MEDIA FROM NORMAL USER
    # -----------------------------------------------------

    if not message.text:

        # Do not send unnecessary AI replies
        if message.photo:
            return

        if message.audio:
            return

        if message.video:
            return

        if message.voice:
            return

        if message.document:
            return

        return

    text = message.text.strip()

    if not text:
        return

    # -----------------------------------------------------
    # RATE LIMIT
    # -----------------------------------------------------

    if user and is_flooding(
        user.id
    ):

        last_busy = context.user_data.get(
            "last_busy",
            0
        )

        if time.time() - last_busy > 8:

            context.user_data[
                "last_busy"
            ] = time.time()

            await message.reply_text(
                "⏳ একটু ধীরে বলুন, আমি শুনছি। 🙂"
            )

        return

    # -----------------------------------------------------
    # PENDING CONTENT
    # -----------------------------------------------------

    pending = get_pending(
        user.id
    )

    if pending:

        row = await search_content(
            text
        )

        if row:

            await message.reply_text(
                "👋 Welcome!\n"
                "⏳ একটু অপেক্ষা করুন, দিচ্ছি..."
            )

            success = await send_saved_content(
                update,
                row
            )

            if success:

                clear_pending(
                    user.id
                )

                await message.reply_text(
                    "আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝"
                )

            return

        await message.reply_text(
            "❌ এই নামে কোনো Saved Content পাইনি।\n"
            "আরেকটু সঠিক নাম লিখে চেষ্টা করুন।"
        )

        return

    # -----------------------------------------------------
    # CONTENT REQUEST
    # -----------------------------------------------------

    if is_content_request(text):

        row = await search_content(
            text
        )

        if row:

            await message.reply_text(
                "👋 Welcome!\n"
                "⏳ একটু অপেক্ষা করুন, দিচ্ছি..."
            )

            success = await send_saved_content(
                update,
                row
            )

            if success:

                await message.reply_text(
                    "আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝"
                )

            return

        set_pending(
            user.id,
            {
                "type": "content_request",
                "asked_at": now().isoformat()
            }
        )

        await message.reply_text(
            "👋 Welcome!\n"
            "⏳ অবশ্যই। Content-এর নামটা লিখুন, "
            "আমি Saved Content থেকে খুঁজে দিচ্ছি।"
        )

        return

    # -----------------------------------------------------
    # TIME
    # -----------------------------------------------------

    nt = normalize(text)

    if any(x in nt for x in [
        "কয়টা বাজে",
        "কত বাজে",
        "সময় কত",
        "time",
        "what time"
    ]):

        await message.reply_text(
            time_text()
        )

        return

    # -----------------------------------------------------
    # DATE
    # -----------------------------------------------------

    if any(x in nt for x in [
        "আজ কত তারিখ",
        "আজকের তারিখ",
        "date",
        "today"
    ]):

        n = now()

        await message.reply_text(
            "📅 আজকের তারিখ: "
            f"{bn(n.strftime('%d-%m-%Y'))}"
        )

        return

    # -----------------------------------------------------
    # WEATHER
    # -----------------------------------------------------

    if any(x in nt for x in [
        "আবহাওয়া",
        "বৃষ্টি হবে",
        "বৃষ্টি",
        "weather"
    ]):

        await message.reply_text(
            await weather_text()
        )

        return

    # -----------------------------------------------------
    # PRAYER
    # -----------------------------------------------------

    if any(x in nt for x in [
        "নামাজের সময়",
        "নামাজ সময়",
        "আজকের নামাজ",
        "prayer time"
    ]):

        await prayer(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # QUICK STATIC REPLIES
    # -----------------------------------------------------

    if any(x in nt for x in [
        "আসসালামু আলাইকুম",
        "assalamu alaikum"
    ]):

        await message.reply_text(
            "ওয়ালাইকুমুস সালাম! 😊"
        )

        return

    if any(x in nt for x in [
        "শুভ সকাল",
        "good morning"
    ]):

        await message.reply_text(
            "🌅 শুভ সকাল! আপনার দিনটি সুন্দর হোক। 😊"
        )

        return

    if any(x in nt for x in [
        "শুভ রাত্রি",
        "good night"
    ]):

        await message.reply_text(
            "🌙 শুভ রাত্রি! ভালোভাবে বিশ্রাম নিন। 😴"
        )

        return

    if any(x in nt for x in [
        "ধন্যবাদ",
        "thanks",
        "thank you"
    ]):

        await message.reply_text(
            "স্বাগতম! 😊"
        )

        return

    # -----------------------------------------------------
    # GEMINI AI
    # -----------------------------------------------------

    reply = await gemini_reply(
        text
    )

    if reply:

        await message.reply_text(
            reply
        )

        return

    # -----------------------------------------------------
    # FALLBACK
    # -----------------------------------------------------

    fallback = random.choice([
        "বুঝলাম 😊 আরেকটু বিস্তারিত বলুন।",
        "ঠিক আছে, বলুন—আমি শুনছি। 🙂",
        "হুম 😊 আপনার কথাটা বুঝতে চেষ্টা করছি।",
        "আচ্ছা! আরও একটু বলুন।"
    ])

    await message.reply_text(
        fallback
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# =========================================================
# STARTUP
# =========================================================

async def post_init(application):

    application.bot_data[
        "automatic_task"
    ] = asyncio.create_task(
        automatic_loop(application)
    )

    print(
        "Bot started successfully."
    )


async def post_shutdown(application):

    task = application.bot_data.get(
        "automatic_task"
    )

    if task:

        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass


# =========================================================
# MAIN
# =========================================================

def main():

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_help
        )
    )

    application.add_handler(
        CommandHandler(
            "admintest",
            admin_test
        )
    )

    application.add_handler(
        CommandHandler(
            "addsong",
            addsong
        )
    )

    application.add_handler(
        CommandHandler(
            "list",
            list_content
        )
    )

    application.add_handler(
        CommandHandler(
            "delete",
            delete_content
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast
        )
    )

    application.add_handler(
        CommandHandler(
            "weather",
            weather
        )
    )

    application.add_handler(
        CommandHandler(
            "prayer",
            prayer
        )
    )

    # ALL normal messages
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
