# ============================================================
#        🇧🇩 BANGLA PUBLIC ALL-IN-ONE TELEGRAM BOT
# ============================================================
# Features:
# 🎵 Songs
# 🎬 Drama / Movie
# 🖼️ Photos / Wallpaper
# 📝 Caption / Status / Quote
# ✍️ Poem
# 😂 Joke / Riddle
# 🎂 Birthday Wish
# ❤️ Love Messages
# 🕌 Islamic / Dua
# 🕐 Bangladesh Time
# 📅 Date / Day
# 🌧️ Weather
# 🕌 Prayer Times
# ⏰ Hourly Time Announcement
# 😴 Midnight Reminder
# 👑 Admin Upload / Delete / Search / Broadcast
# 🔎 Smart Bangla + Banglish Search
# 🚦 Spam Protection
# ============================================================

import os
import re
import sqlite3
import logging
import random
import asyncio
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import aiohttp

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "tomalchowdhury2"
).replace("@", "").strip()

TIMEZONE = ZoneInfo("Asia/Dhaka")

# Narsingdi, Bangladesh
WEATHER_LAT = float(os.getenv("WEATHER_LAT", "24.1344"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "90.7860"))

WEATHER_NAME = os.getenv(
    "WEATHER_NAME",
    "নরসিংদী"
)

PRAYER_CITY = os.getenv(
    "PRAYER_CITY",
    "Narsingdi"
)

PRAYER_COUNTRY = os.getenv(
    "PRAYER_COUNTRY",
    "Bangladesh"
)

# AlAdhan calculation method
PRAYER_METHOD = int(
    os.getenv("PRAYER_METHOD", "1")
)

DB_FILE = "bot_database.db"

# User rate limit
MAX_MESSAGES = 10
RATE_WINDOW_SECONDS = 60

user_message_times = {}

# Avoid duplicate scheduled messages
last_hour_announced = None
last_midnight_reminder = None
last_prayer_message = None


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ============================================================
# BOT TOKEN CHECK
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN পাওয়া যায়নি। GitHub Secrets-এ BOT_TOKEN সেট করুন।"
    )

if ADMIN_ID == 0:
    raise RuntimeError(
        "ADMIN_ID পাওয়া যায়নি। GitHub Secrets-এ ADMIN_ID সেট করুন।"
    )


# ============================================================
# DATABASE
# ============================================================

def db_connect():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_type TEXT,
            title TEXT NOT NULL,
            keywords TEXT,
            category TEXT,
            text_content TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_seen TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# USER SAVE
# ============================================================

def save_user(user):

    if not user:
        return

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            user_id,
            username,
            first_name,
            last_seen
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_seen = excluded.last_seen
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        datetime.now(TIMEZONE).isoformat()
    ))

    conn.commit()
    conn.close()


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(update: Update):

    user = update.effective_user

    return bool(
        user and
        user.id == ADMIN_ID
    )


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize(text):

    if not text:
        return ""

    text = text.lower().strip()

    # Common Bangla request words
    remove_words = [
        "দেন",
        "দাও",
        "দিন",
        "চাই",
        "লাগবে",
        "দিবেন",
        "পাঠান",
        "পাঠাও",
        "দিতে পারবেন",
        "একটা",
        "একটি",
        "আমাকে",
        "ভাই",
        "প্লিজ",
        "please",
        "give",
        "send",
        "me",
        "দেখাও",
        "বলেন",
        "বল",
    ]

    for word in remove_words:
        text = text.replace(word, " ")

    text = re.sub(r"[^\w\s\u0980-\u09FF]", " ", text)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# CATEGORY DETECTION
# ============================================================

CATEGORY_KEYWORDS = {

    "song": [
        "গান",
        "song",
        "music",
        "গানটা",
        "গানটি",
        "সঙ"
    ],

    "drama": [
        "নাটক",
        "drama",
        "নাটকটা"
    ],

    "movie": [
        "মুভি",
        "movie",
        "সিনেমা",
        "film"
    ],

    "photo": [
        "ছবি",
        "photo",
        "picture",
        "pic",
        "ফটো"
    ],

    "wallpaper": [
        "wallpaper",
        "ওয়ালপেপার",
        "ওয়ালপেপার",
        "background"
    ],

    "caption": [
        "caption",
        "ক্যাপশন",
        "কেপশন"
    ],

    "status": [
        "status",
        "স্ট্যাটাস"
    ],

    "quote": [
        "quote",
        "কোট",
        "উক্তি"
    ],

    "poem": [
        "কবিতা",
        "poem"
    ],

    "joke": [
        "জোক",
        "জোকস",
        "joke",
        "হাসির"
    ],

    "riddle": [
        "ধাঁধা",
        "riddle"
    ],

    "birthday": [
        "birthday",
        "জন্মদিন",
        "জন্মদিনের"
    ],

    "love": [
        "love",
        "ভালোবাসা",
        "প্রেম",
        "রোমান্টিক"
    ],

    "sad": [
        "sad",
        "সেড",
        "দুঃখ",
        "মন খারাপ"
    ],

    "attitude": [
        "attitude",
        "অ্যাটিটিউড"
    ],

    "islamic": [
        "islamic",
        "ইসলামিক",
        "ইসলাম",
        "দ্বীনি"
    ],

    "dua": [
        "দোয়া",
        "দুয়া",
        "dua"
    ],
}


def detect_category(text):

    text_lower = text.lower()

    found = []

    for category, words in CATEGORY_KEYWORDS.items():

        for word in words:

            if word.lower() in text_lower:
                found.append(category)
                break

    return found


# ============================================================
# SPECIAL INTENT DETECTION
# ============================================================

def is_time_request(text):

    words = [
        "সময় কত",
        "কয়টা বাজে",
        "কয়টা বাজে",
        "এখন সময়",
        "এখন সময়",
        "time",
        "সময় বল",
        "সময় বল"
    ]

    return any(
        x in text.lower()
        for x in words
    )


def is_date_request(text):

    words = [
        "আজকের তারিখ",
        "আজ কত তারিখ",
        "তারিখ কত",
        "date",
        "আজকে কত তারিখ"
    ]

    return any(
        x in text.lower()
        for x in words
    )


def is_day_request(text):

    words = [
        "আজ কী বার",
        "আজ কি বার",
        "আজকের বার",
        "কোন বার",
        "বার কি",
        "day"
    ]

    return any(
        x in text.lower()
        for x in words
    )


def is_weather_request(text):

    words = [
        "আবহাওয়া",
        "আবহাওয়া",
        "weather",
        "বৃষ্টি",
        "গরম",
        "ঠান্ডা",
        "বৃষ্টি হচ্ছে",
        "গরম লাগছে",
        "ঠান্ডা লাগছে"
    ]

    return any(
        x in text.lower()
        for x in words
    )


def is_prayer_request(text):

    words = [
        "নামাজের সময়",
        "নামাজের সময়",
        "নামাজের টাইম",
        "আজকের নামাজ",
        "ওয়াক্ত",
        "ওয়াক্ত",
        "ফজর",
        "জোহর",
        "যোহর",
        "আসর",
        "মাগরিব",
        "এশা",
        "prayer"
    ]

    return any(
        x in text.lower()
        for x in words
    )


# ============================================================
# TIME RESPONSE
# ============================================================

def current_time_text():

    now = datetime.now(TIMEZONE)

    return (
        "🕐 <b>এখন সময়</b>\n\n"
        f"🇧🇩 বাংলাদেশ সময়: "
        f"<b>{now.strftime('%I:%M:%S %p')}</b>\n"
        f"📍 স্থান: <b>নরসিংদী</b>"
    )


# ============================================================
# DATE RESPONSE
# ============================================================

BANGLA_DAYS = {
    "Saturday": "শনিবার",
    "Sunday": "রবিবার",
    "Monday": "সোমবার",
    "Tuesday": "মঙ্গলবার",
    "Wednesday": "বুধবার",
    "Thursday": "বৃহস্পতিবার",
    "Friday": "শুক্রবার",
}


def date_text():

    now = datetime.now(TIMEZONE)

    day = BANGLA_DAYS.get(
        now.strftime("%A"),
        now.strftime("%A")
    )

    return (
        "📅 <b>আজকের তারিখ</b>\n\n"
        f"🗓️ {now.strftime('%d-%m-%Y')}\n"
        f"📌 আজ <b>{day}</b>\n"
        f"🇧🇩 বাংলাদেশ সময়"
    )


# ============================================================
# WEATHER API
# ============================================================

async def get_weather():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={WEATHER_LAT}"
        f"&longitude={WEATHER_LON}"
        "&current=temperature_2m,relative_humidity_2m,"
        "apparent_temperature,precipitation,weather_code,"
        "wind_speed_10m"
        "&timezone=Asia%2FDhaka"
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

                return await response.json()

    except Exception as e:

        logger.error(
            "Weather error: %s",
            e
        )

        return None


def weather_description(code):

    mapping = {

        0: "☀️ পরিষ্কার আকাশ",

        1: "🌤️ সামান্য মেঘলা",

        2: "⛅ আংশিক মেঘলা",

        3: "☁️ মেঘলা",

        45: "🌫️ কুয়াশা",

        48: "🌫️ কুয়াশা",

        51: "🌦️ হালকা গুঁড়ি বৃষ্টি",

        53: "🌦️ মাঝারি গুঁড়ি বৃষ্টি",

        55: "🌧️ বেশি গুঁড়ি বৃষ্টি",

        61: "🌧️ হালকা বৃষ্টি",

        63: "🌧️ মাঝারি বৃষ্টি",

        65: "🌧️ ভারী বৃষ্টি",

        80: "🌦️ বৃষ্টির সম্ভাবনা",

        81: "🌧️ বৃষ্টি",

        82: "🌧️ ভারী বৃষ্টি",

        95: "⛈️ বজ্রসহ বৃষ্টি",

        96: "⛈️ বজ্রসহ বৃষ্টি",

        99: "⛈️ বজ্রসহ ভারী বৃষ্টি",
    }

    return mapping.get(
        code,
        "🌤️ আবহাওয়া"
    )


async def weather_text():

    data = await get_weather()

    if not data:

        return (
            "🌤️ এখন আবহাওয়ার তথ্য পাওয়া যাচ্ছে না।\n"
            "একটু পরে আবার চেষ্টা করুন।"
        )

    current = data.get(
        "current",
        {}
    )

    temp = current.get(
        "temperature_2m",
        "?"
    )

    feels = current.get(
        "apparent_temperature",
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

    condition = weather_description(code)

    return (
        f"📍 <b>{WEATHER_NAME}</b>\n\n"
        f"{condition}\n"
        f"🌡️ তাপমাত্রা: <b>{temp}°C</b>\n"
        f"🤒 অনুভূত হচ্ছে: <b>{feels}°C</b>\n"
        f"💧 আর্দ্রতা: <b>{humidity}%</b>\n"
        f"💨 বাতাস: <b>{wind} km/h</b>"
    )


# ============================================================
# PRAYER API
# ============================================================

async def get_prayer_times():

    today = datetime.now(
        TIMEZONE
    ).strftime("%d-%m-%Y")

    url = (
        f"https://api.aladhan.com/v1/timingsByCity/"
        f"{today}"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        f"&method={PRAYER_METHOD}"
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

                return data.get(
                    "data",
                    {}
                ).get(
                    "timings",
                    {}
                )

    except Exception as e:

        logger.error(
            "Prayer error: %s",
            e
        )

        return None


async def prayer_text():

    timings = await get_prayer_times()

    if not timings:

        return (
            "🕌 আজকের নামাজের সময় এখন পাওয়া যাচ্ছে না।\n"
            "একটু পরে আবার চেষ্টা করুন।"
        )

    names = [
        ("ফজর", "Fajr"),
        ("সূর্যোদয়", "Sunrise"),
        ("যোহর", "Dhuhr"),
        ("আসর", "Asr"),
        ("মাগরিব", "Maghrib"),
        ("এশা", "Isha"),
    ]

    lines = [
        "🕌 <b>আজকের নামাজের সময়</b>",
        "",
        "📍 নরসিংদী, বাংলাদেশ",
        ""
    ]

    for bn, key in names:

        value = timings.get(
            key,
            "--"
        )

        lines.append(
            f"🕐 {bn}: <b>{value}</b>"
        )

    return "\n".join(lines)


# ============================================================
# BUILT-IN TEXT RESPONSES
# ============================================================

TEXT_RESPONSES = {

    "sad": [
        "😔 মন খারাপ? সব সময় খারাপ থাকে না—সময় বদলায়। ❤️",
        "🥺 কিছু অনুভূতি শুধু চুপচাপ অনুভব করতে হয়। নিজের যত্ন নিন। ❤️",
        "😞 মন খারাপ হলে একটু বিশ্রাম নিন, প্রিয় কারও সাথে কথা বলুন। 🌸",
    ],

    "love": [
        "❤️ ভালোবাসা সুন্দর, যখন সেখানে সম্মান আর যত্ন থাকে। 🌸",
        "💖 প্রিয় মানুষকে সময় দেওয়া অনেক বড় ভালোবাসা।",
        "🥰 যত্ন, বিশ্বাস আর সম্মান—ভালো সম্পর্কের সুন্দর অংশ। ❤️",
    ],

    "attitude": [
        "😎 নিজের পথে চলুন, অন্যের সাথে নিজেকে তুলনা করার দরকার নেই।",
        "🔥 চুপ থাকা মানে দুর্বল হওয়া নয়।",
        "😎 নিজের সম্মান নিজের কাছেই সবচেয়ে গুরুত্বপূর্ণ।",
    ],

    "joke": [
        "😂 শিক্ষক: পড়া শিখেছ? ছাত্র: স্যার, পড়া তো শিখেছি, কিন্তু মনে রাখতে পারিনি! 🤣",
        "🤣 ফোন: আমার ব্যাটারি শেষ। আমি: আমিও শেষ! 😭😂",
        "😂 পরীক্ষার আগে সবাই বলে—সহজ হবে। পরীক্ষার হলে গিয়ে সবাই দর্শনশাস্ত্রী হয়ে যায়! 😆",
    ],

    "riddle": [
        "🧩 ধাঁধা: কোন জিনিস যত কাটবেন তত বড় হবে? 🤔\n\nউত্তর চাইলে লিখুন: <b>উত্তর</b>",
        "🧩 ধাঁধা: দাঁত আছে কিন্তু কামড়াতে পারে না—সেটা কী? 😄",
    ],

    "morning": [
        "🌅 শুভ সকাল! আজকের দিনটা সুন্দর হোক। ❤️",
        "☀️ সুপ্রভাত! হাসি দিয়ে দিন শুরু করুন। 😊",
    ],

    "night": [
        "🌙 শুভ রাত্রি! ভালোভাবে বিশ্রাম নিন। 😴",
        "🌃 রাত হয়েছে, আজকের জন্য বিশ্রাম নিন। শুভ রাত্রি। ❤️",
    ],

    "birthday": [
        "🎂 শুভ জন্মদিন! আপনার দিনটি আনন্দ, হাসি ও সুন্দর মুহূর্তে ভরে উঠুক। 🎉❤️",
        "🥳 Happy Birthday! নতুন বছরটা সুন্দর হোক। 🎂✨",
    ],

    "islamic": [
        "🕌 আল্লাহ আমাদের সবাইকে সঠিক পথে চলার তাওফিক দিন। আমিন। 🤲",
        "🤲 আল্লাহ আমাদের পরিবার ও প্রিয়জনদের হেফাজত করুন। আমিন।",
    ],

    "dua": [
        "🤲 আল্লাহ আমাদের গুনাহ মাফ করুন, শান্তি দিন এবং হালাল রিজিক দান করুন। আমিন।",
        "🕌 হে আল্লাহ, আমাদের ও আমাদের পরিবারকে হেফাজত করুন। আমিন। 🤲",
    ],

    "poem": [
        "✍️ কবিতা চাইলে Admin-এর যোগ করা কবিতা থেকে খুঁজে দিতে পারি।",
    ],

    "quote": [
        "💭 সুন্দর কথা মানুষের দিনটাকে একটু হলেও সুন্দর করতে পারে। ❤️",
    ],

    "status": [
        "📝 আপনার জন্য Status খুঁজছি...",
    ],

    "love_message": [
        "❤️ প্রিয় মানুষকে ভালোবাসার পাশাপাশি সম্মান ও যত্নও দিন।",
    ],
}


# ============================================================
# WEATHER CHAT REPLIES
# ============================================================

RAIN_REPLIES = [
    "🌧️ আহা, বৃষ্টি! দারুণ আবহাওয়া—আজ তোমার পাশে তোমার প্রিয় মানুষটা থাকলে আরও ভালো লাগত। ❤️",
    "🌧️ বৃষ্টি পড়ছে? ☕ একটা গরম পানীয় আর সুন্দর একটা গান হতে পারে দারুণ সঙ্গী। 🎵",
    "🌧️ আজ বৃষ্টির দিন! সাবধানে থাকুন, আর ছাতা নিতে ভুলবেন না। ☂️",
]

HOT_REPLIES = [
    "🥵 আজ অনেক গরম? পানি খান 💧 আর সম্ভব হলে ঠান্ডা জায়গায় থাকুন। 🍋🥤",
    "☀️ গরম অনেক! প্রিয় মানুষকে বলুন লেবুর শরবত বানাতে 😄🍋",
    "🥵 প্রচণ্ড গরমে বেশি পানি পান করুন এবং রোদ থেকে একটু দূরে থাকুন। 💧",
]


# ============================================================
# SEARCH DATABASE
# ============================================================

def similarity(a, b):

    return SequenceMatcher(
        None,
        normalize(a),
        normalize(b)
    ).ratio()


def search_posts(query, categories=None):

    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM posts
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    query_normalized = normalize(query)

    results = []

    for row in rows:

        title = normalize(
            row["title"] or ""
        )

        keywords = normalize(
            row["keywords"] or ""
        )

        category = normalize(
            row["category"] or ""
        )

        text_content = normalize(
            row["text_content"] or ""
        )

        full_text = " ".join([
            title,
            keywords,
            category,
            text_content
        ])

        score = 0

        # Exact title
        if query_normalized == title:
            score += 100

        # Query inside title
        if query_normalized and query_normalized in title:
            score += 80

        # Query inside keywords
        if query_normalized and query_normalized in keywords:
            score += 70

        # Query inside text
        if query_normalized and query_normalized in text_content:
            score += 50

        # Word matching
        for word in query_normalized.split():

            if len(word) < 2:
                continue

            if word in full_text:
                score += 10

        # Fuzzy
        score += int(
            similarity(
                query_normalized,
                full_text[:500]
            ) * 30
        )

        if categories:

            if category in categories:
                score += 60

        if score > 20:

            results.append(
                (score, row)
            )

    results.sort(
        key=lambda x: x[0],
        reverse=True
    )

    return [
        row
        for score, row in results[:5]
    ]


# ============================================================
# SEND POST
# ============================================================

async def send_post(
    update,
    post
):

    chat_id = update.effective_chat.id

    file_id = post["file_id"]

    file_type = post["file_type"]

    title = post["title"]

    text_content = post["text_content"]

    caption = (
        f"📌 <b>{title}</b>\n\n"
        f"🏷️ {post['category'] or 'Content'}"
    )

    try:

        if file_type == "photo":

            await update.get_bot().send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        elif file_type == "video":

            await update.get_bot().send_video(
                chat_id=chat_id,
                video=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        elif file_type == "audio":

            await update.get_bot().send_audio(
                chat_id=chat_id,
                audio=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        elif file_type == "document":

            await update.get_bot().send_document(
                chat_id=chat_id,
                document=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

        elif file_type == "text":

            await update.get_bot().send_message(
                chat_id=chat_id,
                text=(
                    f"📝 <b>{title}</b>\n\n"
                    f"{text_content}"
                ),
                parse_mode=ParseMode.HTML
            )

    except Exception as e:

        logger.error(
            "Send post error: %s",
            e
        )


# ============================================================
# RATE LIMIT
# ============================================================

def check_rate_limit(user_id):

    now = datetime.now(
        TIMEZONE
    )

    times = user_message_times.get(
        user_id,
        []
    )

    times = [
        t for t in times
        if (
            now - t
        ).total_seconds()
        < RATE_WINDOW_SECONDS
    ]

    if len(times) >= MAX_MESSAGES:

        user_message_times[user_id] = times

        return False

    times.append(now)

    user_message_times[user_id] = times

    return True


# ============================================================
# START
# ============================================================

async def start(update, context):

    save_user(
        update.effective_user
    )

    await update.message.reply_text(
        "👋 <b>Welcome!</b>\n\n"
        "আমি তোমার বাংলা Smart Bot 🤖🇧🇩\n\n"
        "তুমি সরাসরি যা চাইবে লিখতে পারো।\n\n"
        "🎵 গান\n"
        "🎬 নাটক\n"
        "🎞️ মুভি\n"
        "🖼️ ছবি\n"
        "📝 Caption\n"
        "😂 Joke\n"
        "🧩 ধাঁধা\n"
        "🕌 নামাজের সময়\n"
        "🌤️ আবহাওয়া\n"
        "🕐 বর্তমান সময়\n\n"
        "শুধু লিখে পাঠাও। ❤️",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# HELP
# ============================================================

async def help_command(update, context):

    await update.message.reply_text(
        "🤖 <b>আমি কী কী করতে পারি?</b>\n\n"
        "🎵 গান দেন\n"
        "🎬 নাটক দেন\n"
        "🎞️ মুভি দেন\n"
        "🖼️ ছবি দেন\n"
        "🌄 Wallpaper দেন\n"
        "😔 Sad Caption দেন\n"
        "❤️ Love Caption দেন\n"
        "😎 Attitude Caption দেন\n"
        "📝 Facebook Caption দেন\n"
        "💬 Status দেন\n"
        "💭 Quote দেন\n"
        "✍️ কবিতা দেন\n"
        "😂 Joke বলেন\n"
        "🧩 ধাঁধা দেন\n"
        "🎂 Birthday Wish দেন\n"
        "🕌 Islamic পোস্ট দেন\n"
        "🤲 দোয়া দেন\n"
        "🌧️ আজ বৃষ্টি হচ্ছে\n"
        "☀️ আজ অনেক গরম\n"
        "🕌 আজকের নামাজের সময়\n"
        "🕐 এখন কয়টা বাজে\n"
        "📅 আজকের তারিখ কত\n\n"
        "যা দরকার সরাসরি লিখুন। 😊",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# ADMIN HELP
# ============================================================

async def admin_command(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।\n\n"
            f"🆘 সমস্যা হলে @{ADMIN_USERNAME}-এর সাথে যোগাযোগ করুন।"
        )

        return

    await update.message.reply_text(
        "👑 <b>Admin Panel</b>\n\n"
        "📤 Media upload:\n"
        "<code>Title | Keywords | Category</code>\n\n"
        "উদাহরণ:\n"
        "<code>Tum Hi Ho | tum hi ho, arijit, গান | song</code>\n\n"
        "📝 Text content:\n"
        "<code>/addtext Sad Caption | sad, caption, সেড ক্যাপশন | caption | মন খারাপের ক্যাপশন...</code>\n\n"
        "📊 /stats\n"
        "📋 /list\n"
        "🔎 /search keyword\n"
        "🗑️ /delete ID\n"
        "📢 /broadcast message\n"
        "🕌 /prayer\n",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# ADD TEXT
# ============================================================

async def add_text(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    raw = update.message.text

    raw = raw.replace(
        "/addtext",
        "",
        1
    ).strip()

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 4:

        await update.message.reply_text(
            "❌ Format ঠিক হয়নি।\n\n"
            "/addtext Title | Keywords | Category | Text"
        )

        return

    title = parts[0]
    keywords = parts[1]
    category = parts[2]
    text_content = "|".join(parts[3:]).strip()

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO posts (
            file_id,
            file_type,
            title,
            keywords,
            category,
            text_content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        "",
        "text",
        title,
        keywords,
        category,
        text_content,
        datetime.now(TIMEZONE).isoformat()
    ))

    post_id = cur.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Text content added!\n\n"
        f"🆔 ID: {post_id}\n"
        f"📌 {title}\n"
        f"🏷️ {category}"
    )


# ============================================================
# MEDIA UPLOAD
# ============================================================

async def handle_admin_media(update, context):

    if not is_admin(update):
        return

    message = update.message

    caption = (
        message.caption or ""
    ).strip()

    if not caption:

        await message.reply_text(
            "❌ Media-এর caption এভাবে দিন:\n\n"
            "Title | Keywords | Category\n\n"
            "উদাহরণ:\n"
            "Tum Hi Ho | tum hi ho, arijit, গান | song"
        )

        return

    parts = [
        x.strip()
        for x in caption.split("|")
    ]

    if len(parts) < 3:

        await message.reply_text(
            "❌ Format ভুল।\n\n"
            "Title | Keywords | Category"
        )

        return

    title = parts[0]
    keywords = parts[1]
    category = parts[2]

    file_id = None
    file_type = None

    if message.photo:

        file_id = message.photo[-1].file_id
        file_type = "photo"

    elif message.video:

        file_id = message.video.file_id
        file_type = "video"

    elif message.audio:

        file_id = message.audio.file_id
        file_type = "audio"

    elif message.document:

        file_id = message.document.file_id
        file_type = "document"

    else:

        return

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO posts (
            file_id,
            file_type,
            title,
            keywords,
            category,
            text_content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        file_id,
        file_type,
        title,
        keywords,
        category,
        "",
        datetime.now(TIMEZONE).isoformat()
    ))

    post_id = cur.lastrowid

    conn.commit()
    conn.close()

    await message.reply_text(
        f"✅ Content Added!\n\n"
        f"🆔 ID: {post_id}\n"
        f"📌 {title}\n"
        f"🏷️ {category}\n\n"
        f"🔎 এখন User এটা বিভিন্নভাবে search করতে পারবে।"
    )


# ============================================================
# STATS
# ============================================================

async def stats_command(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ Admin only."
        )

        return

    conn = db_connect()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    posts = conn.execute(
        "SELECT COUNT(*) FROM posts"
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        "📊 <b>Bot Statistics</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"📦 Content: <b>{posts}</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# LIST
# ============================================================

async def list_command(update, context):

    if not is_admin(update):
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT id, title, category
        FROM posts
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📭 কোনো content নেই।"
        )

        return

    lines = [
        "📋 <b>Latest Content</b>",
        ""
    ]

    for row in rows:

        lines.append(
            f"🆔 {row['id']} — "
            f"{row['title']} "
            f"[{row['category']}]"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# SEARCH ADMIN
# ============================================================

async def admin_search(update, context):

    if not is_admin(update):
        return

    query = update.message.text.replace(
        "/search",
        "",
        1
    ).strip()

    if not query:

        await update.message.reply_text(
            "🔎 /search keyword"
        )

        return

    posts = search_posts(query)

    if not posts:

        await update.message.reply_text(
            "❌ কিছু পাওয়া যায়নি।"
        )

        return

    lines = [
        "🔎 <b>Search Result</b>",
        ""
    ]

    for post in posts:

        lines.append(
            f"🆔 {post['id']} — "
            f"{post['title']} "
            f"[{post['category']}]"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


# ============================================================
# DELETE
# ============================================================

async def delete_command(update, context):

    if not is_admin(update):
        return

    raw = update.message.text.replace(
        "/delete",
        "",
        1
    ).strip()

    if not raw.isdigit():

        await update.message.reply_text(
            "❌ উদাহরণ:\n/delete 12"
        )

        return

    post_id = int(raw)

    conn = db_connect()

    cur = conn.cursor()

    cur.execute(
        "DELETE FROM posts WHERE id = ?",
        (post_id,)
    )

    deleted = cur.rowcount

    conn.commit()
    conn.close()

    if deleted:

        await update.message.reply_text(
            f"🗑️ Content ID {post_id} deleted."
        )

    else:

        await update.message.reply_text(
            "❌ এই ID পাওয়া যায়নি।"
        )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_command(update, context):

    if not is_admin(update):
        return

    message = update.message.text.replace(
        "/broadcast",
        "",
        1
    ).strip()

    if not message:

        await update.message.reply_text(
            "📢 /broadcast আপনার message"
        )

        return

    conn = db_connect()

    rows = conn.execute(
        "SELECT user_id FROM users"
    ).fetchall()

    conn.close()

    sent = 0
    failed = 0

    await update.message.reply_text(
        "📢 Broadcast শুরু হয়েছে..."
    )

    for row in rows:

        try:

            await context.bot.send_message(
                chat_id=row["user_id"],
                text=message
            )

            sent += 1

            await asyncio.sleep(
                0.05
            )

        except Exception:

            failed += 1

    await update.message.reply_text(
        f"✅ Broadcast শেষ।\n\n"
        f"📤 Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )


# ============================================================
# SPECIAL BUILT-IN INTENTS
# ============================================================

def detect_special_reply(text):

    lower = text.lower()

    # Morning
    if (
        "শুভ সকাল" in lower or
        "সুপ্রভাত" in lower or
        "good morning" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["morning"]
        )

    # Night
    if (
        "শুভ রাত্রি" in lower or
        "শুভ রাত" in lower or
        "good night" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["night"]
        )

    # Birthday
    if (
        "birthday wish" in lower or
        "birthday" in lower or
        "জন্মদিনের শুভেচ্ছা" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["birthday"]
        )

    # Joke
    if (
        "জোক" in lower or
        "জোকস" in lower or
        "joke" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["joke"]
        )

    # Riddle
    if (
        "ধাঁধা" in lower or
        "riddle" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["riddle"]
        )

    # Islamic
    if (
        "ইসলামিক পোস্ট" in lower or
        "islamic post" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["islamic"]
        )

    # Dua
    if (
        "দোয়া" in lower or
        "দুয়া" in lower or
        "dua" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["dua"]
        )

    # Love message
    if (
        "ভালোবাসার মেসেজ" in lower or
        "love message" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["love_message"]
        )

    # Sad
    if (
        "sad caption" in lower or
        "সেড ক্যাপশন" in lower or
        "দুঃখের ক্যাপশন" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["sad"]
        )

    # Love
    if (
        "love caption" in lower or
        "লাভ ক্যাপশন" in lower or
        "ভালোবাসার ক্যাপশন" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["love"]
        )

    # Attitude
    if (
        "attitude caption" in lower or
        "অ্যাটিটিউড ক্যাপশন" in lower
    ):
        return random.choice(
            TEXT_RESPONSES["attitude"]
        )

    # Rain
    if (
        "বৃষ্টি হচ্ছে" in lower or
        "আজকে বৃষ্টি" in lower or
        "আজ বৃষ্টি" in lower
    ):
        return random.choice(
            RAIN_REPLIES
        )

    # Hot
    if (
        "অনেক গরম" in lower or
        "আজকে গরম" in lower or
        "আজ গরম" in lower
    ):
        return random.choice(
            HOT_REPLIES
        )

    return None


# ============================================================
# MAIN MESSAGE HANDLER
# ============================================================

async def handle_message(
    update,
    context
):

    if not update.message:
        return

    user = update.effective_user

    save_user(user)

    user_id = user.id

    # Rate limit
    if not check_rate_limit(user_id):

        await update.message.reply_text(
            "⏳ একটু ধীরে ভাই 😅\n\n"
            "এক মিনিটে অনেকগুলো message এসেছে।\n"
            "একটু অপেক্ষা করুন, তারপর আবার চেষ্টা করুন। ❤️"
        )

        return

    text = (
        update.message.text or ""
    ).strip()

    if not text:
        return

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    if is_time_request(text):

        await update.message.reply_text(
            current_time_text(),
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    if is_date_request(text):

        await update.message.reply_text(
            date_text(),
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # DAY
    # --------------------------------------------------------

    if is_day_request(text):

        now = datetime.now(
            TIMEZONE
        )

        day = BANGLA_DAYS.get(
            now.strftime("%A"),
            now.strftime("%A")
        )

        await update.message.reply_text(
            f"📅 আজ <b>{day}</b>। 🇧🇩",
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # PRAYER
    # --------------------------------------------------------

    if is_prayer_request(text):

        await update.message.reply_text(
            "🕌 আজকের নামাজের সময় খুঁজছি..."
        )

        result = await prayer_text()

        await update.message.reply_text(
            result,
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # WEATHER
    # --------------------------------------------------------

    if (
        "আবহাওয়া" in text.lower()
        or
        "আবহাওয়া" in text.lower()
        or
        "weather" in text.lower()
    ):

        await update.message.reply_text(
            "🌤️ আবহাওয়ার তথ্য দেখছি..."
        )

        result = await weather_text()

        await update.message.reply_text(
            result,
            parse_mode=ParseMode.HTML
        )

        return

    # --------------------------------------------------------
    # SPECIAL CHAT
    # --------------------------------------------------------

    special = detect_special_reply(text)

    if special:

        await update.message.reply_text(
            special
        )

        # Also try database content for category
        categories = detect_category(text)

        if categories:

            posts = search_posts(
                text,
                categories
            )

            if posts:

                await asyncio.sleep(
                    0.5
                )

                for post in posts[:2]:

                    await send_post(
                        update,
                        post
                    )

        return

    # --------------------------------------------------------
    # CATEGORY SEARCH
    # --------------------------------------------------------

    categories = detect_category(text)

    # Search text
    clean_query = normalize(text)

    # Welcome / wait message
    await update.message.reply_text(
        "👋 Welcome!\n"
        "⏳ একটু অপেক্ষা করুন, দিচ্ছি... 😊"
    )

    await asyncio.sleep(
        0.7
    )

    posts = search_posts(
        clean_query,
        categories
    )

    # --------------------------------------------------------
    # RESULTS
    # --------------------------------------------------------

    if posts:

        for post in posts[:3]:

            await send_post(
                update,
                post
            )

            await asyncio.sleep(
                0.3
            )

        return

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    await update.message.reply_text(
        "😔 দুঃখিত, এখনো এই request-এর "
        "সাথে মিলে কোনো content পাওয়া যায়নি।\n\n"
        "📝 অন্যভাবে লিখে চেষ্টা করুন।\n"
        "👑 অথবা Admin-এর কাছে নতুন content যোগ করতে বলুন।\n\n"
        f"🆘 সমস্যা হলে @{ADMIN_USERNAME}-এর সাথে যোগাযোগ করুন।"
    )


# ============================================================
# HOURLY + MIDNIGHT + PRAYER JOB
# ============================================================

async def scheduled_job(context):

    global last_hour_announced
    global last_midnight_reminder
    global last_prayer_message

    now = datetime.now(
        TIMEZONE
    )

    # --------------------------------------------------------
    # GET USERS
    # --------------------------------------------------------

    conn = db_connect()

    users = conn.execute(
        "SELECT user_id FROM users"
    ).fetchall()

    conn.close()

    # --------------------------------------------------------
    # EVERY FULL HOUR
    # --------------------------------------------------------

    if now.minute == 0:

        hour_key = now.strftime(
            "%Y-%m-%d-%H"
        )

        if last_hour_announced != hour_key:

            last_hour_announced = hour_key

            time_message = (
                "🕐 <b>সময় ঘোষণা</b>\n\n"
                f"এখন বাংলাদেশ সময় "
                f"<b>{now.strftime('%I:%M %p')}</b>। 🇧🇩\n\n"
                "⏰ নতুন এক ঘণ্টা শুরু হলো।"
            )

            for user in users:

                try:

                    await context.bot.send_message(
                        chat_id=user["user_id"],
                        text=time_message,
                        parse_mode=ParseMode.HTML
                    )

                    await asyncio.sleep(
                        0.05
                    )

                except Exception:
                    pass

    # --------------------------------------------------------
    # MIDNIGHT
    # --------------------------------------------------------

    if (
        now.hour == 0
        and
        now.minute == 0
    ):

        midnight_key = now.strftime(
            "%Y-%m-%d"
        )

        if last_midnight_reminder != midnight_key:

            last_midnight_reminder = midnight_key

            message = (
                "🌙 রাত ১২টা বাজে গেছে!\n\n"
                "😴 এখনো ঘুমান নাই আপনি?\n"
                "ঘুমানোর সময় হয়েছে। ভালোভাবে বিশ্রাম নিন। ❤️"
            )

            for user in users:

                try:

                    await context.bot.send_message(
                        chat_id=user["user_id"],
                        text=message
                    )

                    await asyncio.sleep(
                        0.05
                    )

                except Exception:
                    pass

    # --------------------------------------------------------
    # STUDY REMINDER 7 PM
    # --------------------------------------------------------

    if (
        now.hour == 19
        and
        now.minute == 0
    ):

        study_key = now.strftime(
            "%Y-%m-%d"
        )

        # Reuse midnight variable carefully
        study_attr = getattr(
            scheduled_job,
            "last_study",
            None
        )

        if study_attr != study_key:

            scheduled_job.last_study = study_key

            message = (
                "📚⏰ এখন পড়ার সময়!\n\n"
                "👦👧 বাচ্চারা, মোবাইলটা একটু পাশে রাখো "
                "এবং পড়তে বসো। 📖✏️"
            )

            for user in users:

                try:

                    await context.bot.send_message(
                        chat_id=user["user_id"],
                        text=message
                    )

                    await asyncio.sleep(
                        0.05
                    )

                except Exception:
                    pass

    # --------------------------------------------------------
    # PRAYER REMINDER
    # --------------------------------------------------------

    if now.second <= 5:

        timings = await get_prayer_times()

        if timings:

            prayer_map = {
                "Fajr": "ফজর",
                "Dhuhr": "যোহর",
                "Asr": "আসর",
                "Maghrib": "মাগরিব",
                "Isha": "এশা"
            }

            current_hm = now.strftime(
                "%H:%M"
            )

            for key, bn in prayer_map.items():

                prayer_time = timings.get(
                    key,
                    ""
                )

                if prayer_time == current_hm:

                    prayer_key = (
                        f"{now.strftime('%Y-%m-%d')}-"
                        f"{key}-{current_hm}"
                    )

                    if last_prayer_message != prayer_key:

                        last_prayer_message = prayer_key

                        message = (
                            f"🕌 <b>{bn} এর সময় হয়েছে</b>\n\n"
                            "📢 আজানের সময় হয়েছে।\n"
                            "🤲 নামাজের জন্য প্রস্তুত হোন।"
                        )

                        for user in users:

                            try:

                                await context.bot.send_message(
                                    chat_id=user["user_id"],
                                    text=message,
                                    parse_mode=ParseMode.HTML
                                )

                                await asyncio.sleep(
                                    0.05
                                )

                            except Exception:
                                pass


# ============================================================
# PRAYER COMMAND
# ============================================================

async def prayer_command(update, context):

    result = await prayer_text()

    await update.message.reply_text(
        result,
        parse_mode=ParseMode.HTML
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
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
            "help",
            help_command
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "addtext",
            add_text
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    application.add_handler(
        CommandHandler(
            "list",
            list_command
        )
    )

    application.add_handler(
        CommandHandler(
            "search",
            admin_search
        )
    )

    application.add_handler(
        CommandHandler(
            "delete",
            delete_command
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_command
        )
    )

    application.add_handler(
        CommandHandler(
            "prayer",
            prayer_command
        )
    )

    # Admin media
    application.add_handler(
        MessageHandler(
            filters.PHOTO |
            filters.VIDEO |
            filters.AUDIO |
            filters.Document.ALL,
            handle_admin_media
        )
    )

    # Normal text
    application.add_handler(
        MessageHandler(
            filters.TEXT &
            ~filters.COMMAND,
            handle_message
        )
    )

    # Error
    application.add_error_handler(
        error_handler
    )

    # Scheduler: every 5 seconds
    if application.job_queue:

        application.job_queue.run_repeating(
            scheduled_job,
            interval=5,
            first=5
        )

    logger.info(
        "🇧🇩 Bot started successfully."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    main()
