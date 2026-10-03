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
    raise RuntimeError("BOT_TOKEN পাওয়া যায়নি।")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY পাওয়া যায়নি।")


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

    return datetime.now(
        TZ
    ).strftime(
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

    title = chat.title or ""
    username = chat.username or ""

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
        title,
        username,
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
    limit=12
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

    rows = list(
        reversed(rows)
    )

    result = []

    for row in rows:

        if row["role"] not in (
            "user",
            "assistant"
        ):
            continue

        result.append({
            "role": row["role"],
            "content": row["content"]
        })

    return result


# =========================================================
# BOT STATE
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
        DO UPDATE SET
            value=excluded.value
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

        if update.effective_message:

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

    data = rate_data.setdefault(
        user_id,
        []
    )

    data[:] = [
        t for t in data
        if now - t < 5
    ]

    if len(data) >= 7:
        return False

    data.append(now)

    return True


# =========================================================
# TEXT NORMALIZER
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
# CONTENT SYSTEM
# =========================================================

CONTENT_WORDS = [

    "গান",
    "গানটা",
    "গানটি",
    "song",
    "songs",

    "নাটক",
    "নাটকটা",
    "নাটকটি",
    "drama",
    "dramas",

    "মুভি",
    "মুভিটা",
    "মুভিটি",
    "movie",
    "movies",

    "সিনেমা",
    "সিনেমাটা",
    "cinema",

    "ভিডিও",
    "ভিডিওটা",
    "ভিডিওটি",
    "video",
    "videos",

    "ডান্স",
    "dance",

    "ছবি",
    "ছবিটা",
    "photo",
    "photos",
    "picture",
]


REQUEST_WORDS = [

    "দাও",
    "দেন",
    "দিবে",
    "চাই",
    "লাগবে",
    "পাঠাও",
    "পাঠিয়ে",
    "পাঠান",
    "send",
    "give",
    "want",
    "please",
    "দেখাও",
    "দেখতে চাই",
]


def is_content_request(text):

    t = normalize_text(text)

    has_content = any(
        word in t
        for word in CONTENT_WORDS
    )

    has_request = any(
        word in t
        for word in REQUEST_WORDS
    )

    return (
        has_content
        and has_request
    )


def extract_content_query(text):

    t = normalize_text(text)

    words_to_remove = (
        CONTENT_WORDS
        + REQUEST_WORDS
        + [
            "একটা",
            "একটি",
            "আমাকে",
            "আমার",
            "প্লিজ",
            "please",
            "টাও",
            "টা",
            "টি",
            "দিতে",
            "হবে",
            "করে",
            "দাও",
            "দেন",
            "আমাকে",
        ]
    )

    for word in words_to_remove:

        t = re.sub(
            r"\b" + re.escape(word) + r"\b",
            " ",
            t
        )

    t = re.sub(
        r"\s+",
        " ",
        t
    ).strip()

    return t


def search_content(query):

    query = normalize_text(
        query
    )

    if not query:
        return None

    # প্রথমে পুরো phrase খোঁজা
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

    # এরপর শব্দ ধরে খোঁজা
    words = [
        w
        for w in query.split()
        if len(w) >= 2
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

    sql = f"""
        SELECT *
        FROM contents
        WHERE {" OR ".join(conditions)}
        ORDER BY id DESC
        LIMIT 1
    """

    return db_execute(
        sql,
        tuple(params),
        fetchone=True
    )


async def send_saved_content(
    update,
    row
):

    message = update.effective_message

    try:

        title = row["title"]
        media_type = row["media_type"]
        file_id = row["file_id"]

        await message.reply_text(
            f"🎬 {title}\n\n"
            "⏳ পাঠানো হচ্ছে..."
        )

        if media_type == "photo":

            await message.reply_photo(
                photo=file_id
            )

        elif media_type == "video":

            await message.reply_video(
                video=file_id,
                supports_streaming=True
            )

        elif media_type == "audio":

            await message.reply_audio(
                audio=file_id
            )

        elif media_type == "document":

            await message.reply_document(
                document=file_id
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
            "CONTENT SEND ERROR:",
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


def set_pending_content(
    chat_id,
    user_id
):

    pending_content[chat_id] = {
        "user_id": user_id,
        "time": time.time()
    }


def get_pending_content(
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

    if (
        time.time()
        - data["time"]
        > 600
    ):

        pending_content.pop(
            chat_id,
            None
        )

        return False

    return True


def clear_pending_content(
    chat_id
):

    pending_content.pop(
        chat_id,
        None
    )


# =========================================================
# FIXED NATURAL REPLIES
# =========================================================

def get_fixed_reply(text):

    t = normalize_text(text)

    # -----------------------------
    # Greeting
    # -----------------------------

    greetings = {
        "হাই",
        "হ্যালো",
        "হাই হাই",
        "হ্যালো হ্যালো",
        "hi",
        "hello",
        "hey",
        "হাই কেমন আছো",
        "হ্যালো কেমন আছো",
        "hi how are you",
        "hello how are you",
    }

    if t in greetings:

        return (
            "হাই! 👋 "
            "কেমন আছেন? "
            "কীভাবে সাহায্য করতে পারি?"
        )


    # -----------------------------
    # Assalamu Alaikum
    # -----------------------------

    if t in [
        "আসসালামু আলাইকুম",
        "আসসালামু আলাইকুম সবাই",
        "assalamualaikum",
        "assalamu alaikum",
    ]:

        return (
            "ওয়ালাইকুম আসসালাম! 🤝 "
            "কেমন আছেন?"
        )


    # -----------------------------
    # How are you
    # -----------------------------

    if t in [
        "কেমন আছো",
        "কেমন আছেন",
        "কেমন আছ",
        "কেমন আছিস",
        "how are you",
        "how r u",
    ]:

        return (
            "আমি ভালো আছি! 😊 "
            "আপনি কেমন আছেন?"
        )


    # -----------------------------
    # Thanks
    # -----------------------------

    if t in [
        "ধন্যবাদ",
        "অনেক ধন্যবাদ",
        "thanks",
        "thank you",
        "থ্যাংকস",
        "অনেক থ্যাংকস",
    ]:

        return (
            "স্বাগতম! 😊 "
            "যখন দরকার হবে বলবেন।"
        )


    # -----------------------------
    # Goodbye
    # -----------------------------

    if t in [
        "বিদায়",
        "বাই",
        "bye",
        "goodbye",
        "আচ্ছা বাই",
        "ঠিক আছে বাই",
    ]:

        return (
            "ঠিক আছে! 👋 "
            "ভালো থাকবেন।"
        )


    # -----------------------------
    # Electricity
    # -----------------------------

    electricity_words = [

        "বিদ্যুৎ নাই",
        "বিদ্যুৎ নেই",
        "কারেন্ট নাই",
        "কারেন্ট নেই",
        "electricity নাই",
        "electricity নেই",
        "current নাই",
        "current নেই",
        "light নাই",
        "লাইট নাই",
        "লাইট নেই",
    ]

    if any(
        word in t
        for word in electricity_words
    ):

        return (
            "বিদ্যুৎ না থাকার কয়েকটি কারণ হতে পারে—"
            "লোডশেডিং, লাইনে ত্রুটি, সাবস্টেশনের সমস্যা "
            "অথবা রক্ষণাবেক্ষণ। "
            "আপনার এলাকার নির্দিষ্ট কারণ জানতে "
            "স্থানীয় বিদ্যুৎ অফিসের আপডেট দেখা সবচেয়ে নির্ভরযোগ্য।"
        )


    # -----------------------------
    # Internet
    # -----------------------------

    internet_words = [

        "ইন্টারনেট নাই",
        "ইন্টারনেট নেই",
        "নেট নাই",
        "নেট নেই",
        "internet নাই",
        "internet নেই",
        "wifi নাই",
        "wifi নেই",
        "ওয়াইফাই নাই",
        "ওয়াইফাই নেই",
    ]

    if any(
        word in t
        for word in internet_words
    ):

        return (
            "ইন্টারনেট না থাকার কারণ হতে পারে "
            "ISP-এর সমস্যা, রাউটার বা মোবাইল ডাটার সমস্যা, "
            "নেটওয়ার্ক congestion অথবা maintenance। "
            "আগে Wi-Fi/Data বন্ধ করে আবার চালু করে "
            "অন্য একটি website বা app খুলে পরীক্ষা করে দেখুন।"
        )


    return None


# =========================================================
# OPENAI
# =========================================================

SYSTEM_PROMPT = """
তুমি একটি Telegram group assistant bot।

তোমার কাজ হলো মানুষের কথার অর্থ বুঝে স্বাভাবিক,
helpful এবং context-aware উত্তর দেওয়া।

খুব গুরুত্বপূর্ণ নিয়ম:

1. ব্যবহারকারী সরাসরি প্রশ্ন করলে সরাসরি প্রশ্নের উত্তর দেবে।

2. অকারণে:
"আচ্ছা"
"ঠিক আছে"
"বলুন"
"আরও একটু বলুন"
"আমি শুনছি"
এই ধরনের generic উত্তর দেবে না।

3. ব্যবহারকারী সাধারণভাবে কথা বললে স্বাভাবিকভাবে কথা বলবে।

4. ব্যবহারকারী বাংলা লিখলে বাংলায় উত্তর দেবে।

5. Banglish হলে সহজ Banglish বা বাংলা ব্যবহার করবে।

6. English হলে English-এ উত্তর দিতে পারবে।

7. ব্যবহারকারীর প্রশ্ন না বুঝলে প্রয়োজনীয় clarification করবে।

8. নিজের কাছে কোনো file বা media আছে বলে মিথ্যা বলবে না।

9. Telegram saved content system-এর কাজ নিজে করার চেষ্টা করবে না।

10. গান, নাটক, মুভি, ভিডিও বা ছবি চাওয়া হলে program-এর saved-content
system সেই কাজ করবে।

11. Content delivery সফল হলে program নিজে closing message পাঠাবে।
তুমি সেই exact closing message লিখবে না।

12. কোনো প্রশ্নের উত্তর জানা না থাকলে নিশ্চিত তথ্যের মতো মিথ্যা বলবে না।

13. ব্যবহারকারী "হাই" বা "হ্যালো" বললে স্বাভাবিক greeting দেবে।
Generic "আরও একটু বলুন" বলবে না।

উত্তর সংক্ষিপ্ত, পরিষ্কার এবং ব্যবহারকারীর কথার সাথে সরাসরি সম্পর্কিত রাখবে।
"""


async def ai_reply(
    chat_id,
    user_text
):

    history = get_history(
        chat_id,
        limit=12
    )

    input_messages = []

    for item in history:

        role = item["role"]

        if role not in (
            "user",
            "assistant"
        ):
            continue

        input_messages.append({
            "role": role,
            "content": item["content"]
        })

    # বর্তমান message history-তে না থাকলে যোগ করা
    if (
        not input_messages
        or input_messages[-1]["content"]
        != user_text
        or input_messages[-1]["role"]
        != "user"
    ):

        input_messages.append({
            "role": "user",
            "content": user_text
        })

    try:

        response = await client.responses.create(

            model=OPENAI_MODEL,

            instructions=SYSTEM_PROMPT,

            input=input_messages,

            max_output_tokens=500,
        )

        answer = getattr(
            response,
            "output_text",
            None
        )

        if not answer:

            return (
                "দুঃখিত, এখন উত্তর তৈরি করতে পারছি না। "
                "একটু পরে আবার চেষ্টা করুন।"
            )

        return answer.strip()

    except Exception as e:

        print(
            "OPENAI ERROR:",
            repr(e)
        )

        return (
            "😔 দুঃখিত, এই মুহূর্তে AI response দিতে সমস্যা হচ্ছে। "
            "একটু পরে আবার চেষ্টা করুন।"
        )


# =========================================================
# WEATHER
# =========================================================

async def get_weather():

    lat = 24.1344
    lon = 90.7860

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}"
        f"&longitude={lon}"
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

            async with session.get(
                url
            ) as response:

                if response.status != 200:
                    return None

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
            0
        )

        description = weather_description(
            code
        )

        return (
            f"🌤️ {PRAYER_CITY} Weather\n\n"
            f"{description}\n"
            f"🌡️ তাপমাত্রা: {temp}°C\n"
            f"💧 আর্দ্রতা: {humidity}%\n"
            f"💨 বাতাস: {wind} km/h"
        )

    except Exception as e:

        print(
            "WEATHER ERROR:",
            repr(e)
        )

        return None


def weather_description(code):

    code = int(
        code or 0
    )

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

    if code in (71, 73, 75, 77):
        return "❄️ তুষার"

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

            async with session.get(
                url
            ) as response:

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
# COMMANDS
# =========================================================

async def start_command(
    update,
    context
):

    await update.effective_message.reply_text(

        "👋 Welcome!\n\n"

        "আমি আপনার Telegram AI Assistant।\n"

        "বাংলা, Banglish বা English-এ কথা বলতে পারেন।"
    )


async def admin_command(
    update,
    context
):

    if not await admin_only(update):
        return

    await update.effective_message.reply_text(

        "👑 Admin Panel\n\n"

        "/addsong - নতুন content যোগ করুন\n"
        "/list - saved content দেখুন\n"
        "/stats - bot statistics\n"
        "/delete ID - content delete\n"
        "/broadcast TEXT - সবাইকে message\n"
        "/admintest - admin test"
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

        "📥 এখন একটি Video / Audio / Photo / Document পাঠান।\n\n"

        "তারপর আমি title চাইব।"
    )


async def list_command(
    update,
    context
):

    if not await admin_only(update):
        return

    rows = db_execute("""

        SELECT
            id,
            title,
            media_type,
            category,
            created_at

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
        "SELECT COUNT(*) AS c FROM users",
        fetchone=True
    )["c"]

    chats = db_execute(
        "SELECT COUNT(*) AS c FROM chats",
        fetchone=True
    )["c"]

    contents = db_execute(
        "SELECT COUNT(*) AS c FROM contents",
        fetchone=True
    )["c"]

    messages = db_execute(
        "SELECT COUNT(*) AS c FROM messages",
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
            "❌ ID অবশ্যই number হতে হবে।"
        )

        return

    row = db_execute("""

        SELECT title
        FROM contents
        WHERE id=?

    """, (
        content_id,
    ), fetchone=True)

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

            "ব্যবহার করুন:\n"
            "/broadcast আপনার message"
        )

        return

    rows = db_execute(
        "SELECT chat_id FROM chats",
        fetch=True
    )

    success = 0
    failed = 0

    for row in rows:

        chat_id = row["chat_id"]

        try:

            await context.bot.send_message(
                chat_id=chat_id,
                text=text
            )

            success += 1

            await asyncio.sleep(
                0.05
            )

        except Exception as e:

            print(
                "BROADCAST ERROR:",
                chat_id,
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

    weather = await get_weather()

    if weather:

        await update.effective_message.reply_text(
            weather
        )

    else:

        await update.effective_message.reply_text(
            "❌ Weather data পাওয়া যাচ্ছে না।"
        )


async def prayer_command(
    update,
    context
):

    prayer = await get_prayer_times()

    if prayer:

        await update.effective_message.reply_text(
            prayer
        )

    else:

        await update.effective_message.reply_text(
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
        "এখন content-এর Title লিখুন।"
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

    if (
        "গান" in t
        or "song" in t
    ):
        return "song"

    if (
        "নাটক" in t
        or "drama" in t
    ):
        return "drama"

    if (
        "মুভি" in t
        or "movie" in t
        or "সিনেমা" in t
    ):
        return "movie"

    if (
        "ডান্স" in t
        or "dance" in t
    ):
        return "dance"

    if (
        "ভিডিও" in t
        or "video" in t
    ):
        return "video"

    if (
        "ছবি" in t
        or "photo" in t
    ):
        return "photo"

    return "other"


# =========================================================
# NORMAL MESSAGE
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

    # =====================================================
    # ADMIN MEDIA
    # =====================================================

    handled = await handle_admin_media(
        update,
        context
    )

    if handled:
        return

    # =====================================================
    # TEXT ONLY
    # =====================================================

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # =====================================================
    # ADMIN TITLE
    # =====================================================

    handled = await handle_admin_title(
        update,
        context
    )

    if handled:
        return

    # =====================================================
    # RATE LIMIT
    # =====================================================

    if not check_rate_limit(
        user.id
    ):

        await message.reply_text(
            "⏳ একটু ধীরে বলুন, আমি শুনছি। 🙂"
        )

        return

    # =====================================================
    # PENDING CONTENT
    # =====================================================

    if get_pending_content(
        chat.id,
        user.id
    ):

        row = search_content(
            text
        )

        if row:

            clear_pending_content(
                chat.id
            )

            await send_saved_content(
                update,
                row
            )

            return

        await message.reply_text(

            "❌ এই নামে কোনো saved content পাওয়া যায়নি।\n\n"
            "আরেকবার নামটি লিখে চেষ্টা করুন।"
        )

        return

    # =====================================================
    # CONTENT REQUEST
    # =====================================================

    if is_content_request(
        text
    ):

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

        set_pending_content(
            chat.id,
            user.id
        )

        await message.reply_text(

            "❌ এই নামে কোনো saved content এখনো পাওয়া যায়নি।\n\n"

            "📝 যে content চান তার নামটি লিখুন।\n"
            "আমি আবার search করছি।"
        )

        return

    # =====================================================
    # FIXED NATURAL REPLIES
    # =====================================================

    fixed_reply = get_fixed_reply(
        text
    )

    if fixed_reply:

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
            fixed_reply
        )

        await message.reply_text(
            fixed_reply
        )

        return

    # =====================================================
    # WEATHER
    # =====================================================

    normalized = normalize_text(
        text
    )

    weather_words = [

        "আবহাওয়া",
        "weather",
        "বৃষ্টি হবে",
        "বৃষ্টি আসবে",
        "আজ বৃষ্টি",
        "তাপমাত্রা কত",
        "temperature কত",
        "temperature",
    ]

    if any(
        word in normalized
        for word in weather_words
    ):

        weather = await get_weather()

        if weather:

            await message.reply_text(
                weather
            )

        else:

            await message.reply_text(
                "❌ Weather data পাওয়া যাচ্ছে না।"
            )

        return

    # =====================================================
    # PRAYER NATURAL QUESTION
    # =====================================================

    prayer_words = [

        "নামাজের সময়",
        "নামাজের ওয়াক্ত",
        "নামাজ কখন",
        "আজকের নামাজ",
        "prayer time",
        "prayer times",
    ]

    if any(
        word in normalized
        for word in prayer_words
    ):

        prayer = await get_prayer_times()

        if prayer:

            await message.reply_text(
                prayer
            )

        else:

            await message.reply_text(
                "❌ নামাজের সময় পাওয়া যাচ্ছে না।"
            )

        return

    # =====================================================
    # SAVE USER MESSAGE
    # =====================================================

    save_message(
        chat.id,
        user.id,
        "user",
        text
    )

    # =====================================================
    # AI
    # =====================================================

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
# HOURLY AUTOMATIC MESSAGES
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
        "🌆 শুভ সন্ধ্যা সবাইকে! 🌆\n"
        "দিনটা সুন্দরভাবে শেষ হোক। ❤️",

    19:
        "📚 Study Time!\n"
        "যারা পড়াশোনা করছেন, মনোযোগ দিয়ে পড়ুন। 💪📖",

    22:
        "🌙 রাত ১০টা!\n"
        "অনেক রাত হয়েছে—সময়মতো ঘুমানোর চেষ্টা করুন। 😴",
}


GENERIC_HOURS = {

    11:
        "🕐 এখন সময় ১১:০০ বাজে",

    13:
        "🕐 এখন সময় ১:০০ বাজে",

    14:
        "🕐 এখন সময় ২:০০ বাজে",

    15:
        "🕐 এখন সময় ৩:০০ বাজে",

    17:
        "🕐 এখন সময় ৫:০০ বাজে",

    20:
        "🕐 এখন সময় ৮:০০ বাজে",

    21:
        "🕐 এখন সময় ৯:০০ বাজে",

    23:
        "🕐 এখন সময় ১১:০০ বাজে",
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

                current_key = now.strftime(
                    "%Y-%m-%d-%H"
                )

                last_hour = get_state(
                    "last_auto_hour"
                )

                if last_hour != current_key:

                    if hour in SPECIAL_MESSAGES:

                        text = SPECIAL_MESSAGES[
                            hour
                        ]

                    elif hour in GENERIC_HOURS:

                        text = GENERIC_HOURS[
                            hour
                        ]

                    else:

                        text = None

                    if text:

                        rows = db_execute(
                            "SELECT chat_id FROM chats",
                            fetch=True
                        )

                        for row in rows:

                            chat_id = row[
                                "chat_id"
                            ]

                            try:

                                await application.bot.send_message(
                                    chat_id=chat_id,
                                    text=text
                                )

                                await asyncio.sleep(
                                    0.05
                                )

                            except Exception as e:

                                print(
                                    "AUTO MESSAGE ERROR:",
                                    chat_id,
                                    repr(e)
                                )

                        set_state(
                            "last_auto_hour",
                            current_key
                        )

        except Exception as e:

            print(
                "HOURLY LOOP ERROR:",
                repr(e)
            )

        await asyncio.sleep(
            20
        )


# =========================================================
# POST INIT
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
        "BOT STARTED"
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
# ERROR HANDLER
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
        .token(
            BOT_TOKEN
        )
        .post_init(
            post_init
        )
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # Normal messages
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
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


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
