import os
import re
import sqlite3
import logging
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

BOT_TOKEN = os.getenv("BOT_TOKEN")

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

ADMIN_USERNAME = os.getenv(
    "ADMIN_USERNAME",
    "tomalchowdhury2"
).replace("@", "")

PRAYER_CITY = os.getenv(
    "PRAYER_CITY",
    "Narsingdi"
)

PRAYER_COUNTRY = os.getenv(
    "PRAYER_COUNTRY",
    "Bangladesh"
)

TIMEZONE = ZoneInfo("Asia/Dhaka")

DB_FILE = "bot_database.db"

WEATHER_LAT = 24.1344
WEATHER_LON = 90.7860
WEATHER_NAME = "Narsingdi"


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# =========================================================
# DATABASE
# =========================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT NOT NULL,
            file_type TEXT NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            created_at TEXT NOT NULL
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


def save_user(user):

    if not user:
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users
        (user_id, username, first_name, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_seen = excluded.last_seen
    """, (
        user.id,
        user.username,
        user.first_name,
        datetime.now(TIMEZONE).isoformat()
    ))

    conn.commit()
    conn.close()


def save_content(
    file_id,
    file_type,
    title,
    category
):

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO contents
        (file_id, file_type, title, category, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        file_id,
        file_type,
        title,
        category,
        datetime.now(TIMEZONE).isoformat()
    ))

    conn.commit()
    conn.close()


def search_content(title, category=None):

    conn = db()
    cur = conn.cursor()

    if category:

        cur.execute("""
            SELECT id, file_id, file_type, title, category
            FROM contents
            WHERE category = ?
        """, (category,))

    else:

        cur.execute("""
            SELECT id, file_id, file_type, title, category
            FROM contents
        """)

    rows = cur.fetchall()

    conn.close()

    if not rows:
        return None

    title_clean = normalize(title)

    best = None
    best_score = 0

    for row in rows:

        db_title = normalize(row[3])

        score = SequenceMatcher(
            None,
            title_clean,
            db_title
        ).ratio()

        if title_clean in db_title:
            score += 0.45

        if db_title in title_clean:
            score += 0.25

        if score > best_score:
            best_score = score
            best = row

    if best_score >= 0.45:
        return best

    return None


# =========================================================
# NORMALIZE TEXT
# =========================================================

def normalize(text):

    if not text:
        return ""

    text = text.lower().strip()

    replacements = {
        "gaan": "গান",
        "gan": "গান",
        "natok": "নাটক",
        "nattok": "নাটক",
        "movie": "মুভি",
        "cinema": "মুভি",
        "song": "গান",
        "drama": "নাটক",
        "wallpaper": "ওয়ালপেপার",
        "photo": "ছবি",
        "pic": "ছবি",
        "picture": "ছবি",
        "caption": "ক্যাপশন",
        "status": "স্ট্যাটাস",
        "good morning": "শুভ সকাল",
        "good afternoon": "শুভ দুপুর",
        "good evening": "শুভ সন্ধ্যা",
        "good night": "শুভ রাত্রি",
        "thank you": "ধন্যবাদ",
        "thanks": "ধন্যবাদ",
        "hello": "হ্যালো",
        "hi": "হাই",
        "hey": "হাই",
        "net": "নেট",
        "wifi": "ওয়াইফাই",
        "current": "কারেন্ট",
        "electricity": "কারেন্ট",
        "bristi": "বৃষ্টি",
        "brishti": "বৃষ্টি",
        "gorom": "গরম",
        "mon kharap": "মন খারাপ",
        "valo": "ভালো",
        "bhalo": "ভালো",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text)

    return text


# =========================================================
# ADMIN
# =========================================================

def is_admin(update):

    if not update.effective_user:
        return False

    return update.effective_user.id == ADMIN_ID


# =========================================================
# CATEGORY DETECTION
# =========================================================

CATEGORY_KEYWORDS = {

    "song": [
        "গান",
        "গান দেন",
        "গান দাও",
        "গান চাই",
        "গান লাগবে",
        "song",
        "music"
    ],

    "drama": [
        "নাটক",
        "নাটক দেন",
        "নাটক দাও",
        "নাটক চাই",
        "নাটক লাগবে",
        "drama",
        "natok"
    ],

    "movie": [
        "মুভি",
        "সিনেমা",
        "movie",
        "film"
    ],

    "photo": [
        "ছবি",
        "ছবি দেন",
        "photo",
        "picture",
        "pic"
    ],

    "wallpaper": [
        "ওয়ালপেপার",
        "wallpaper"
    ],

    "caption": [
        "ক্যাপশন",
        "caption",
        "ফেসবুক ক্যাপশন"
    ],

    "status": [
        "স্ট্যাটাস",
        "status"
    ],

    "quote": [
        "উক্তি",
        "কোট",
        "quote"
    ],

    "poem": [
        "কবিতা",
        "poem"
    ],

    "joke": [
        "জোক",
        "জোকস",
        "joke",
        "মজা"
    ],

    "riddle": [
        "ধাঁধা",
        "riddle"
    ],

    "birthday": [
        "জন্মদিন",
        "birthday"
    ],

    "love": [
        "ভালোবাসা",
        "love",
        "লাভ"
    ],

    "sad": [
        "sad",
        "দুঃখ",
        "মন খারাপ"
    ],

    "attitude": [
        "attitude",
        "অ্যাটিটিউড"
    ],

    "islamic": [
        "ইসলামিক",
        "islamic"
    ],

    "dua": [
        "দোয়া",
        "দোয়া",
        "dua"
    ]
}


def detect_category(text):

    text = normalize(text)

    for category, keywords in CATEGORY_KEYWORDS.items():

        for keyword in keywords:

            if normalize(keyword) in text:
                return category

    return None


# =========================================================
# CONTENT REQUEST DETECTION
# =========================================================

def is_content_request(text):

    category = detect_category(text)

    if not category:
        return False

    request_words = [
        "দেন",
        "দাও",
        "চাই",
        "লাগবে",
        "পাঠাও",
        "দিবেন",
        "দিন",
        "পাই",
        "নেন",
        "show",
        "give"
    ]

    text_n = normalize(text)

    for word in request_words:

        if normalize(word) in text_n:
            return True

    return category in [
        "song",
        "drama",
        "movie",
        "photo",
        "wallpaper"
    ]


# =========================================================
# TIME
# =========================================================

def now():

    return datetime.now(TIMEZONE)


def time_string():

    return now().strftime("%I:%M %p").lstrip("0")


def date_string():

    return now().strftime("%a, %b %d")


def time_header():

    return (
        f"🕐 **এখন সময় {time_string()}।**\n"
        f"📅 {date_string()}\n"
        f"🇧🇩 Narsingdi Time"
    )


# =========================================================
# GENERAL CHAT REPLIES
# =========================================================

GENERAL_REPLIES = {

    "হাই": [
        "👋 Hello ভাই! 😄\nকেমন আছেন?",
        "😎 Hello! হাজির আছি ভাই!",
        "👋 হ্যালো ভাই! আজকে কী খবর?"
    ],

    "হ্যালো": [
        "👋 Hello ভাই! 😊",
        "😄 হ্যালো! বলুন কী খবর?",
        "🤖 Hello! আমি আছি।"
    ],

    "কেমন আছো": [
        "😎 আমি তো একদম Ready ভাই!",
        "🤖 আমার তো সবসময়ই ভালো! আপনাদের সাথে কথা বলছি তো 😄",
        "😊 ভালো আছি ভাই। আপনার খবর কী?"
    ],

    "কি করো": [
        "🤖 আপনাদের Message-এর অপেক্ষায় বসে আছি ভাই! 😎",
        "😄 Group পাহারা দিচ্ছি ভাই!",
        "👀 কে কী বলে সেটা শুনছি আর Reply দিচ্ছি!"
    ],

    "ভালো লাগছে": [
        "😊 এটা শুনে আমারও ভালো লাগছে!",
        "😄 তাহলে আজকের Mood একদম জমজমাট!",
        "❤️ আপনাদের ভালো লাগাটাই তো আসল ব্যাপার!"
    ],

    "মন খারাপ": [
        "😔 আরে ভাই, মন খারাপ করে বসে থাকবেন না।",
        "💙 একটু বিশ্রাম নিন, পছন্দের কিছু করুন। আশা করি মনটা ভালো হয়ে যাবে।",
        "😊 খারাপ সময় বেশিক্ষণ থাকে না—একটু হাসি দেন দেখি!"
    ],

    "আজকে যামু না": [
        "😂 ঠিক আছে ভাই, আজকের Plan Cancel!",
        "😄 আচ্ছা, আজকে না গেলে কালকে কিন্তু অজুহাত চলবে না!",
        "🤣 আজকের Attendance আপনাকে ছাড়াই হয়ে যাবে মনে হয়!"
    ],

    "ঘুমাইতেছি": [
        "😴 ঠিক আছে ভাই, ফোনটাকেও এবার একটু ঘুমাতে দেন! 😂",
        "🌙 Good Night তাহলে!",
        "😂 এত তাড়াতাড়ি? আচ্ছা যান, ঘুমান!"
    ],

    "খাইছো": [
        "😂 আমি তো Digital ভাই, আমার খাবার হলো আপনাদের Message!",
        "🤖 আমার খাওয়া লাগে না, কিন্তু আপনি খেয়েছেন তো?",
        "🍛 আগে আপনি খান ভাই!"
    ]
}


def find_general_reply(text):

    text_n = normalize(text)

    for keyword, replies in GENERAL_REPLIES.items():

        if normalize(keyword) in text_n:

            return random.choice(replies)

    return None


# =========================================================
# WEATHER / POWER / INTERNET
# =========================================================

def special_environment_reply(text):

    t = normalize(text)

    if "বৃষ্টি" in t:

        return random.choice([
            "🌧️ হ্যাঁ ভাই, আজ তো বৃষ্টির আমেজ! ☔😄\nবাইরে গেলে ছাতা নিতে ভুলবেন না।",
            "☔ বৃষ্টি শুরু হলে কিন্তু চা আর আড্ডার Season শুরু! 😂\nবাইরে গেলে সাবধানে যাবেন।",
            "🌧️ বৃষ্টির দিনে একটু ঠান্ডা ঠান্ডা Feel হচ্ছে! 😄\nছাতা সঙ্গে রাখবেন ভাই।"
        ])

    if "কারেন্ট" in t or "বিদ্যুৎ" in t:

        return random.choice([
            "⚡ আরে ভাই, কারেন্টও দেখি আজকে ছুটিতে গেছে! 😂\nএকটু ধৈর্য ধরুন, ফিরে আসুক আবার।",
            "💡 কারেন্ট নেই? তাহলে আজকে মোবাইলের Battery-টাই আসল সম্পদ! 😂",
            "⚡ কারেন্টও আজকে লুকোচুরি খেলছে মনে হয়! 😄"
        ])

    if (
        "নেট নেই" in t
        or "নেট নাই" in t
        or "নেট নেই" in t
        or "ইন্টারনেট" in t
        or "ওয়াইফাই" in t
        or "wifi" in t
    ):

        return random.choice([
            "📶 আরে ভাই, নেটও আজকে লুকোচুরি খেলছে! 😂",
            "📡 নেট নেই? একটু অপেক্ষা করুন, হয়তো আবার ফিরে আসবে। 😄",
            "😂 নেটও আজকে মনে হয় ছুটিতে গেছে!"
        ])

    if "গরম" in t:

        return random.choice([
            "🥵 উফফ! আজকে গরমটা বেশ ভালোই লাগছে!\n💧 বেশি করে পানি পান করুন ভাই।",
            "☀️ গরমের সাথে যুদ্ধ চলছে! 😂\nপানি খান আর রোদে সাবধানে চলুন।",
            "🥵 আজকে সূর্য মনে হয় একটু বেশি Active!"
        ])

    return None


# =========================================================
# FUN RESPONSES
# =========================================================

def fun_reply(text):

    t = normalize(text)

    if "ঘুম" in t:

        return random.choice([
            "😴 ঘুমের সাথে এত বন্ধুত্ব কিসের ভাই? 😂",
            "🛌 বিছানা ডাকছে নাকি ভাই? 😄",
            "😂 ঘুম তো ঘুমই, কিন্তু কাজও তো করতে হবে ভাই!"
        ])

    if "বোর" in t:

        return random.choice([
            "😂 বোর হওয়ার সময় নেই ভাই!",
            "😎 কিছু একটা শুরু করেন, বোরিং পালাবে!",
            "🤣 Group-এ আড্ডা দেন, বোরিং কমে যাবে!"
        ])

    if "হাসি" in t:

        return random.choice([
            "😂 হাসেন হাসেন, হাসির কোনো Tax নাই!",
            "🤣 এটাই তো চাই—সবাই হাসিখুশি থাকুক!",
            "😄 হাসি চলুক!"
        ])

    return None


# =========================================================
# STATIC TEXT CONTENT
# =========================================================

STATIC_CONTENT = {

    "joke": [
        "😂 শিক্ষক: বল তো সবচেয়ে অলস প্রাণী কোনটা?\nছাত্র: স্যার, যে প্রশ্নের উত্তর জানে কিন্তু বলতে চায় না! 🤣"
    ],

    "riddle": [
        "🧩 ধাঁধা: কোন জিনিস যত বেশি শুকায়, তত বেশি ভিজে?\n\n🤔 উত্তর: তোয়ালে!"
    ],

    "quote": [
        "💭 ছোট ছোট চেষ্টা একদিন বড় পরিবর্তন নিয়ে আসে। ❤️"
    ],

    "poem": [
        "✍️ সকাল আসে নতুন আলো নিয়ে,\nনতুন স্বপ্ন জাগে মনে। 🌸"
    ],

    "dua": [
        "🤲 আল্লাহ আমাদের সবাইকে সুস্থ, নিরাপদ ও শান্তিতে রাখুন। আমিন। ❤️"
    ],

    "islamic": [
        "🕌 ভালো কাজ ছোট হলেও নিয়মিত করার চেষ্টা করুন। ❤️"
    ],

    "birthday": [
        "🎂 শুভ জন্মদিন! 🎉\nআপনার জীবন আনন্দ, শান্তি ও সফলতায় ভরে উঠুক। ❤️"
    ],

    "love": [
        "❤️ ভালোবাসা সুন্দর, যখন সেখানে সম্মান, বিশ্বাস ও যত্ন থাকে।"
    ],

    "sad": [
        "😔 মন খারাপ হলে একটু বিশ্রাম নিন এবং কাছের কারও সাথে কথা বলুন। 💙"
    ],

    "attitude": [
        "😎 নিজের মতো থাকুন, নিজের লক্ষ্য নিয়ে এগিয়ে যান।"
    ],

    "caption": [
        "📝 নিজের গল্প নিজেই লিখুন—অন্যের কথায় নিজের পথ বদলাবেন না। 😎"
    ],

    "status": [
        "💬 সময় বদলায়, মানুষও বদলায়—তাই নিজের লক্ষ্যটা ধরে রাখুন।"
    ]
}


def static_reply(category):

    if category in STATIC_CONTENT:

        return random.choice(
            STATIC_CONTENT[category]
        )

    return None


# =========================================================
# WEATHER API
# =========================================================

async def get_weather():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={WEATHER_LAT}"
        f"&longitude={WEATHER_LON}"
        "&current=temperature_2m,weather_code"
    )

    try:

        timeout = aiohttp.ClientTimeout(total=8)

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

                temp = current.get(
                    "temperature_2m"
                )

                code = current.get(
                    "weather_code"
                )

                if temp is None:
                    return None

                weather_names = {
                    0: "পরিষ্কার আকাশ ☀️",
                    1: "আংশিক পরিষ্কার 🌤️",
                    2: "আংশিক মেঘলা ⛅",
                    3: "মেঘলা ☁️",
                    51: "হালকা গুঁড়ি গুঁড়ি বৃষ্টি 🌦️",
                    61: "বৃষ্টি 🌧️",
                    63: "বৃষ্টি 🌧️",
                    65: "ভারী বৃষ্টি 🌧️",
                    80: "বৃষ্টির সম্ভাবনা 🌦️",
                    81: "বৃষ্টি 🌧️",
                    82: "ভারী বৃষ্টি 🌧️",
                }

                condition = weather_names.get(
                    code,
                    "বর্তমান আবহাওয়া"
                )

                return (
                    f"🌦️ **{WEATHER_NAME} Weather**\n\n"
                    f"🌡️ Temperature: {temp}°C\n"
                    f"☁️ Condition: {condition}\n\n"
                    f"🕐 {time_string()}\n"
                    f"📅 {date_string()}"
                )

    except Exception as e:

        logger.warning(
            "Weather error: %s",
            e
        )

        return None


# =========================================================
# PRAYER API
# =========================================================

async def get_prayer_times():

    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        "&method=1"
    )

    try:

        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:
                    return None

                data = await response.json()

                timings = (
                    data
                    .get("data", {})
                    .get("timings", {})
                )

                if not timings:
                    return None

                return {
                    "Fajr": timings.get("Fajr"),
                    "Dhuhr": timings.get("Dhuhr"),
                    "Asr": timings.get("Asr"),
                    "Maghrib": timings.get("Maghrib"),
                    "Isha": timings.get("Isha"),
                }

    except Exception as e:

        logger.warning(
            "Prayer error: %s",
            e
        )

        return None


# =========================================================
# ADMIN CONTENT UPLOAD STATE
# =========================================================

pending_admin_upload = {}


async def handle_admin_media(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return False

    message = update.message

    file_id = None
    file_type = None

    if message.audio:

        file_id = message.audio.file_id
        file_type = "audio"

    elif message.voice:

        file_id = message.voice.file_id
        file_type = "voice"

    elif message.video:

        file_id = message.video.file_id
        file_type = "video"

    elif message.document:

        file_id = message.document.file_id
        file_type = "document"

    elif message.photo:

        file_id = message.photo[-1].file_id
        file_type = "photo"

    if not file_id:
        return False

    pending_admin_upload[update.effective_user.id] = {
        "file_id": file_id,
        "file_type": file_type
    }

    await message.reply_text(
        "📥 কনটেন্ট পেয়েছি!\n\n"
        "🎬 এখন কনটেন্টের নাম লিখুন।\n\n"
        "উদাহরণ:\n"
        "ব্যাচেলর পয়েন্ট\n\n"
        "💡 নাম পাওয়ার পর আমি নিজে থেকেই "
        "Category বুঝে Save করার চেষ্টা করব।"
    )

    return True


def guess_category_from_title(title):

    t = normalize(title)

    if "নাটক" in t:
        return "drama"

    if "গান" in t or "song" in t:
        return "song"

    if "মুভি" in t or "সিনেমা" in t:
        return "movie"

    if "ওয়ালপেপার" in t:
        return "wallpaper"

    if "ছবি" in t or "photo" in t:
        return "photo"

    # Admin যদি শুধু নাম দেয়, default হিসেবে drama
    return "drama"


# =========================================================
# SEND CONTENT
# =========================================================

async def send_saved_content(
    update,
    context,
    row
):

    _, file_id, file_type, title, category = row

    try:

        if file_type == "audio":

            await update.message.reply_audio(
                audio=file_id,
                caption=(
                    f"🎵 **{title}** ❤️\n\n"
                    "ধন্যবাদ! আপনার চাওয়া কনটেন্ট নিন। 😊\n\n"
                    "💙 আরো কিছু লাগলে জানাবেন, "
                    "আমরা আছি আপনার সাথে! 🤝"
                ),
                parse_mode="Markdown"
            )

        elif file_type == "voice":

            await update.message.reply_voice(
                voice=file_id,
                caption=(
                    f"🎧 **{title}** ❤️\n\n"
                    "💙 আরো কিছু লাগলে জানাবেন, "
                    "আমরা আছি আপনার সাথে! 🤝"
                ),
                parse_mode="Markdown"
            )

        elif file_type == "video":

            await update.message.reply_video(
                video=file_id,
                caption=(
                    f"🎬 **{title}** 🍿❤️\n\n"
                    "Thank you! 😊\n"
                    "নিন আপনার চাওয়া কনটেন্ট।\n\n"
                    "💙 আরো কিছু লাগলে জানাবেন, "
                    "আমরা আছি আপনার সাথে! 🤝"
                ),
                parse_mode="Markdown"
            )

        elif file_type == "photo":

            await update.message.reply_photo(
                photo=file_id,
                caption=(
                    f"🖼️ **{title}** ❤️\n\n"
                    "Thank you! 😊\n\n"
                    "💙 আরো কিছু লাগলে জানাবেন, "
                    "আমরা আছি আপনার সাথে! 🤝"
                ),
                parse_mode="Markdown"
            )

        else:

            await update.message.reply_document(
                document=file_id,
                caption=(
                    f"📁 **{title}** ❤️\n\n"
                    "💙 আরো কিছু লাগলে জানাবেন, "
                    "আমরা আছি আপনার সাথে! 🤝"
                ),
                parse_mode="Markdown"
            )

    except Exception as e:

        logger.error(
            "Send content error: %s",
            e
        )

        await update.message.reply_text(
            "❌ কনটেন্ট পাঠাতে সমস্যা হয়েছে।"
        )


# =========================================================
# CONTENT REQUEST FLOW
# =========================================================

pending_user_requests = {}


async def handle_content_request(
    update,
    context,
    category
):

    if category == "song":

        pending_user_requests[
            update.effective_user.id
        ] = "song"

        await update.message.reply_text(
            "🎵 Sure! 😊\n"
            "গানের নামটা বলুন।"
        )

    elif category == "drama":

        pending_user_requests[
            update.effective_user.id
        ] = "drama"

        await update.message.reply_text(
            "🎬 Sure! 😊\n"
            "নাটকের নামটা বলুন।"
        )

    elif category == "movie":

        pending_user_requests[
            update.effective_user.id
        ] = "movie"

        await update.message.reply_text(
            "🎞️ Sure! 😊\n"
            "মুভির নামটা বলুন।"
        )

    elif category == "photo":

        pending_user_requests[
            update.effective_user.id
        ] = "photo"

        await update.message.reply_text(
            "🖼️ Sure! 😊\n"
            "ছবির নামটা বলুন।"
        )

    elif category == "wallpaper":

        pending_user_requests[
            update.effective_user.id
        ] = "wallpaper"

        await update.message.reply_text(
            "🌄 Sure! 😊\n"
            "Wallpaper-এর নামটা বলুন।"
        )

    else:

        content = static_reply(category)

        if content:

            await update.message.reply_text(
                content
            )

        else:

            await update.message.reply_text(
                "😊 অবশ্যই! একটু বিস্তারিত বলুন।"
            )


# =========================================================
# ADMIN COMMANDS
# =========================================================

async def start(update, context):

    save_user(update.effective_user)

    await update.message.reply_text(
        "👋 **Welcome!** 😊\n\n"
        "আমি আপনার Group Assistant Bot। 🤖\n\n"
        "🎵 গান\n"
        "🎬 নাটক\n"
        "🎞️ মুভি\n"
        "🖼️ ছবি\n"
        "🌄 Wallpaper\n"
        "📝 Caption\n"
        "💬 Status\n"
        "😂 Joke\n"
        "🕌 Islamic\n"
        "🕐 সময়\n"
        "🌦️ Weather\n"
        "🕌 নামাজের সময়\n\n"
        "যা দরকার সাধারণভাবেই লিখুন। ❤️",
        parse_mode="Markdown"
    )


async def help_command(update, context):

    await update.message.reply_text(
        "🤖 **Assistant Help**\n\n"
        "Command দেওয়ার প্রয়োজন নেই।\n\n"
        "উদাহরণ:\n"
        "🎵 গান দেন\n"
        "🎬 নাটক দেন\n"
        "🎞️ মুভি দেন\n"
        "🖼️ ছবি দেন\n"
        "🕐 এখন কয়টা বাজে\n"
        "📅 আজ কত তারিখ\n"
        "🕌 আজকের নামাজের সময়\n"
        "🌦️ আজকের আবহাওয়া\n\n"
        "সাধারণ কথাও বলতে পারেন। 😊",
        parse_mode="Markdown"
    )


async def admin_command(update, context):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return

    await update.message.reply_text(
        "👑 **Admin Panel**\n\n"
        "📥 Content Add করতে শুধু Audio/Video/Photo পাঠান।\n"
        "তারপর আমি নাম চাইব।\n\n"
        "📊 /stats\n"
        "📋 /list\n"
        "🗑️ /delete ID",
        parse_mode="Markdown"
    )


async def stats_command(update, context):

    if not is_admin(update):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) FROM users"
    )

    users = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM contents"
    )

    contents = cur.fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"👑 **Admin Stats**\n\n"
        f"👥 Users: {users}\n"
        f"💾 Contents: {contents}",
        parse_mode="Markdown"
    )


async def list_command(update, context):

    if not is_admin(update):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, category
        FROM contents
        ORDER BY id DESC
        LIMIT 30
    """)

    rows = cur.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "📭 এখনো কোনো Content নেই।"
        )

        return

    text = "📋 **Latest Contents**\n\n"

    for row in rows:

        text += (
            f"🆔 {row[0]}\n"
            f"🎬 {row[1]}\n"
            f"📂 {row[2]}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


async def delete_command(update, context):

    if not is_admin(update):
        return

    if not context.args:

        await update.message.reply_text(
            "ব্যবহার:\n/delete ID"
        )

        return

    try:

        content_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ ID সঠিক নয়।"
        )

        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM contents WHERE id = ?",
        (content_id,)
    )

    deleted = cur.rowcount

    conn.commit()
    conn.close()

    if deleted:

        await update.message.reply_text(
            "✅ Content সফলভাবে Delete হয়েছে।"
        )

    else:

        await update.message.reply_text(
            "❌ এই ID-এর কোনো Content পাওয়া যায়নি।"
        )


async def prayer_command(update, context):

    prayers = await get_prayer_times()

    if not prayers:

        await update.message.reply_text(
            "❌ আজকের নামাজের সময় পাওয়া যাচ্ছে না।"
        )

        return

    text = (
        "🕌 **আজকের নামাজের সময়**\n\n"
        f"🌅 Fajr — {prayers['Fajr']}\n"
        f"☀️ Dhuhr — {prayers['Dhuhr']}\n"
        f"🌤️ Asr — {prayers['Asr']}\n"
        f"🌇 Maghrib — {prayers['Maghrib']}\n"
        f"🌙 Isha — {prayers['Isha']}\n\n"
        f"📍 {PRAYER_CITY}, {PRAYER_COUNTRY}"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown"
    )


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user

    save_user(user)

    user_id = user.id

    text = update.message.text

    # -----------------------------------------------------
    # ADMIN MEDIA
    # -----------------------------------------------------

    if is_admin(update):

        handled = await handle_admin_media(
            update,
            context
        )

        if handled:
            return

    # -----------------------------------------------------
    # TEXT ONLY
    # -----------------------------------------------------

    if not text:
        return

    text_clean = text.strip()
    normalized = normalize(text_clean)

    # -----------------------------------------------------
    # ADMIN CONTENT NAME
    # -----------------------------------------------------

    if is_admin(update):

        if user_id in pending_admin_upload:

            upload = pending_admin_upload.pop(
                user_id
            )

            title = text_clean.strip()

            category = guess_category_from_title(
                title
            )

            save_content(
                upload["file_id"],
                upload["file_type"],
                title,
                category
            )

            await update.message.reply_text(
                "✅ **Successfully Saved!** 🎉\n\n"
                f"🎬 Name: {title}\n"
                f"📂 Category: {category}\n\n"
                "💾 কনটেন্টটি সফলভাবে Database-এ "
                "সংরক্ষণ করা হয়েছে।",
                parse_mode="Markdown"
            )

            return

    # -----------------------------------------------------
    # USER PENDING CONTENT NAME
    # -----------------------------------------------------

    if user_id in pending_user_requests:

        category = pending_user_requests.pop(
            user_id
        )

        result = search_content(
            text_clean,
            category
        )

        if result:

            await send_saved_content(
                update,
                context,
                result
            )

        else:

            category_names = {
                "song": "গান",
                "drama": "নাটক",
                "movie": "মুভি",
                "photo": "ছবি",
                "wallpaper": "Wallpaper"
            }

            name = category_names.get(
                category,
                "কনটেন্ট"
            )

            await update.message.reply_text(
                f"😔 দুঃখিত ভাই, **{text_clean}** নামে "
                f"কোনো {name} এখনো পাওয়া যায়নি।\n\n"
                "💡 নামটা আবার একটু ঠিকভাবে লিখে চেষ্টা করুন।",
                parse_mode="Markdown"
            )

        return

    # -----------------------------------------------------
    # TIME REQUEST
    # -----------------------------------------------------

    if (
        "এখন কয়টা" in normalized
        or "এখন কত বাজে" in normalized
        or "সময় কত" in normalized
        or "time" == normalized
        or "current time" in normalized
    ):

        await update.message.reply_text(
            time_header(),
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------------------
    # DATE REQUEST
    # -----------------------------------------------------

    if (
        "আজ কত তারিখ" in normalized
        or "আজকের তারিখ" in normalized
        or "date" == normalized
    ):

        await update.message.reply_text(
            f"📅 আজ **{date_string()}**\n"
            f"🕐 {time_string()}\n"
            f"🇧🇩 Narsingdi Time",
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------------------
    # WEATHER REQUEST
    # -----------------------------------------------------

    if (
        "আবহাওয়া" in normalized
        or "weather" in normalized
        or "তাপমাত্রা" in normalized
    ):

        weather = await get_weather()

        if weather:

            await update.message.reply_text(
                weather,
                parse_mode="Markdown"
            )

        else:

            await update.message.reply_text(
                "🌦️ এখন Weather তথ্য পাওয়া যাচ্ছে না।"
            )

        return

    # -----------------------------------------------------
    # PRAYER REQUEST
    # -----------------------------------------------------

    if (
        "নামাজের সময়" in normalized
        or "নামাজ সময়" in normalized
        or "prayer time" in normalized
    ):

        await prayer_command(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # CONTENT REQUEST
    # -----------------------------------------------------

    if is_content_request(text_clean):

        category = detect_category(
            text_clean
        )

        if category:

            if category in [
                "song",
                "drama",
                "movie",
                "photo",
                "wallpaper"
            ]:

                await handle_content_request(
                    update,
                    context,
                    category
                )

            else:

                content = static_reply(
                    category
                )

                if content:

                    await update.message.reply_text(
                        content
                    )

            return

    # -----------------------------------------------------
    # ENVIRONMENT REPLIES
    # -----------------------------------------------------

    special = special_environment_reply(
        text_clean
    )

    if special:

        await update.message.reply_text(
            special
        )

        return

    # -----------------------------------------------------
    # GENERAL REPLIES
    # -----------------------------------------------------

    general = find_general_reply(
        text_clean
    )

    if general:

        await update.message.reply_text(
            general
        )

        return

    # -----------------------------------------------------
    # FUN REPLIES
    # -----------------------------------------------------

    fun = fun_reply(
        text_clean
    )

    if fun:

        await update.message.reply_text(
            fun
        )

        return

    # -----------------------------------------------------
    # GREETINGS
    # -----------------------------------------------------

    if normalized in [
        "good morning",
        "শুভ সকাল"
    ]:

        await update.message.reply_text(
            "🌅 **Good Morning!** ☀️\n"
            "এবার ঘুম থেকে উঠুন, সকাল হয়েছে। 😊",
            parse_mode="Markdown"
        )

        return

    if normalized in [
        "good afternoon",
        "শুভ দুপুর"
    ]:

        await update.message.reply_text(
            "☀️ **Good Afternoon!** 😊\n"
            "সুন্দর একটা দুপুর কাটুক সবার। ❤️",
            parse_mode="Markdown"
        )

        return

    if normalized in [
        "good evening",
        "শুভ সন্ধ্যা"
    ]:

        await update.message.reply_text(
            "🌆 **Good Evening!** 😊\n"
            "সুন্দর একটা সন্ধ্যা কাটুক সবার। ❤️",
            parse_mode="Markdown"
        )

        return

    if normalized in [
        "good night",
        "শুভ রাত্রি"
    ]:

        await update.message.reply_text(
            "🌙 **Good Night!** 😴\n"
            "ভালোভাবে ঘুমান এবং নিজের যত্ন নিন। ❤️",
            parse_mode="Markdown"
        )

        return

    # -----------------------------------------------------
    # THANK YOU
    # -----------------------------------------------------

    if (
        "ধন্যবাদ" in normalized
        or "thank you" in normalized
        or "thanks" in normalized
    ):

        await update.message.reply_text(
            random.choice([
                "😊 You're Welcome ভাই!",
                "❤️ Welcome! সবসময়!",
                "😎 No Problem ভাই!"
            ])
        )

        return

    # -----------------------------------------------------
    # UNKNOWN
    # -----------------------------------------------------

    await update.message.reply_text(
        random.choice([
            "🤖 হুম ভাই, কথাটা বুঝলাম। আরেকটু সহজ করে বলবেন? 😄",
            "😄 বুঝতে একটু সমস্যা হচ্ছে ভাই। আবার বলুন তো!",
            "🤖 আমি শুনছি ভাই, একটু বিস্তারিত বলুন।"
        ])
    )


# =========================================================
# AUTOMATIC HOURLY SYSTEM
# =========================================================

last_hour_sent = None
last_special_sent = set()


async def automatic_messages(
    context: ContextTypes.DEFAULT_TYPE
):

    global last_hour_sent
    global last_special_sent

    current = now()

    hour = current.hour
    minute = current.minute

    # Telegram chat IDs যেখানে Bot কথা বলবে
    chat_ids = context.application.bot_data.get(
        "active_chats",
        set()
    )

    if not chat_ids:
        return

    # -----------------------------------------------------
    # Every Hour
    # -----------------------------------------------------

    if minute == 0:

        hour_key = current.strftime(
            "%Y-%m-%d-%H"
        )

        if last_hour_sent != hour_key:

            last_hour_sent = hour_key

            message = (
                time_header()
            )

            for chat_id in list(chat_ids):

                try:

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )

                except Exception as e:

                    logger.warning(
                        "Hourly send error: %s",
                        e
                    )

    # -----------------------------------------------------
    # 7 AM
    # -----------------------------------------------------

    if hour == 7 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-07"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "🌅 **Good Morning!** ☀️\n"
                "এবার ঘুম থেকে উঠুন, সকাল হয়ে গেছে। 😊\n"
                "নতুন দিন, নতুন শুরু—দিনটা সুন্দর কাটুক। ❤️"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 8 AM
    # -----------------------------------------------------

    if hour == 8 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-08"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "😴 আর কত ঘুমাবেন ভাই?\n"
                "এবার উঠুন, সকাল তো অনেকটাই হয়ে গেছে! 😂\n"
                "🌞 দিন শুরু করার সময় হয়েছে।"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 9 AM
    # -----------------------------------------------------

    if hour == 9 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-09"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "😴 ঘুমের সাথে এত বন্ধুত্ব কিসের ভাই? 😂\n"
                "এবার উঠুন—দিন কিন্তু এগিয়ে যাচ্ছে! 🌞"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 10 AM
    # -----------------------------------------------------

    if hour == 10 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-10"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "😂 কী ভাই! ১০টা বাজে, এখনো ঘুম?\n"
                "এবার কিন্তু উঠতেই হবে!\n"
                "☀️ সকালটা আর নষ্ট করবেন না।"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 12 PM
    # -----------------------------------------------------

    if hour == 12 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-12"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "☀️ **Good Afternoon!** 😊\n"
                "দুপুর হয়ে গেছে।\n"
                "সময়মতো খাবার খান, পানি পান করুন এবং নিজের যত্ন নিন। ❤️"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 4 PM
    # -----------------------------------------------------

    if hour == 16 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-16"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "🌤️ বিকেল হয়ে গেছে!\n"
                "একটু বিশ্রাম নিন, তারপর প্রয়োজনীয় কাজগুলো শেষ করুন। 😊"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 6 PM
    # -----------------------------------------------------

    if hour == 18 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-18"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "🌆 **Good Evening!** 😊\n"
                "সুন্দর একটা সন্ধ্যা কাটুক সবার। ❤️"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 7 PM STUDY
    # -----------------------------------------------------

    if hour == 19 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-19"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "📚 **Study Time!** 📝\n"
                "পড়াশোনার সময় হয়েছে।\n"
                "📖 কিছুক্ষণ মন দিয়ে পড়ুন—আজকের একটু "
                "পরিশ্রমই আগামী দিনের কাজে আসবে। 💙\n\n"
                "🎯 ফোনটা একটু পাশে রেখে পড়ায় মন দিন। 😊"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 10 PM
    # -----------------------------------------------------

    if hour == 22 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-22"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "😴 কী ভাই, এখনো জেগে আছেন?\n"
                "এবার দিনের কাজ গুছিয়ে ঘুমানোর প্রস্তুতি নিন। 🌙\n"
                "💤 পর্যাপ্ত ঘুম শরীর ও মনকে সতেজ রাখতে সাহায্য করে। ❤️"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message
                    )
                except:
                    pass

    # -----------------------------------------------------
    # 12 AM
    # -----------------------------------------------------

    if hour == 0 and minute == 0:

        key = current.strftime(
            "%Y-%m-%d-00"
        )

        if key not in last_special_sent:

            last_special_sent.add(key)

            message = (
                f"{time_header()}\n\n"
                "🌙 **Good Night!** 😴\n"
                "এখন কিন্তু সত্যিই ঘুমানোর সময়।\n"
                "আর কতক্ষণ জেগে থাকবেন ভাই? 😂\n"
                "💤 ভালোভাবে বিশ্রাম নিন, নিজের যত্ন নিন। ❤️\n\n"
                "🌙 **Sleep well & take care!**"
            )

            for chat_id in list(chat_ids):

                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except:
                    pass


# =========================================================
# TRACK ACTIVE CHATS
# =========================================================

async def track_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_chat:

        context.application.bot_data.setdefault(
            "active_chats",
            set()
        ).add(
            update.effective_chat.id
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    logger.error(
        "Bot error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN পাওয়া যায়নি। GitHub Secret ঠিক আছে কিনা দেখুন।"
        )

    if ADMIN_ID == 0:

        raise RuntimeError(
            "ADMIN_ID পাওয়া যায়নি। GitHub Secret ঠিক আছে কিনা দেখুন।"
        )

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
            "delete",
            delete_command
        )
    )

    application.add_handler(
        CommandHandler(
            "prayer",
            prayer_command
        )
    )

    # Track every chat

    application.add_handler(
        MessageHandler(
            filters.ALL,
            track_chat
        ),
        group=-10
    )

    # Main message handler

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    # Media handler

    application.add_handler(
        MessageHandler(
            filters.VIDEO
            | filters.AUDIO
            | filters.VOICE
            | filters.PHOTO
            | filters.Document.ALL,
            handle_message
        )
    )

    # Error

    application.add_error_handler(
        error_handler
    )

    # Automatic system
    # প্রতি 20 সেকেন্ডে check করবে

    application.job_queue.run_repeating(
        automatic_messages,
        interval=20,
        first=5
    )

    logger.info(
        "Bot started successfully."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
