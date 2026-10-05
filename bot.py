#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram AI Assistant & Media Bot - OpenAI + AdsGram
Admin: @tomalchowdhury2 (ID: 8721334265)

FULL VERSION

Kept features:
- OpenAI AI replies
- Admin media upload -> title -> category -> SQLite save
- Drama/song/video/category search and delivery
- Admin alerts
- Weather and prayer times
- Admin commands
- Group-message handling/logging
- Removes old Telegram webhook before polling
- Saves groups when bot is added
- Hourly automatic reminders
- Exact prayer-time automatic reminders
- Study, sports, work and sleep reminders
- /auto_on and /auto_off per chat

Added:
- AdsGram Bot API ad before media delivery
- Dynamic category system
- Large category system
- Admin add/edit/delete category
- Natural category intent detection
- Fast local replies before OpenAI
- Bengali/Banglish understanding
- Creator/Boss identity replies
- Bot home/location reply
- Rain / heat / winter smart replies
- Food / cooking / bathing / sleeping replies
- Funny replies
- Apology replies
- Anti-fighting replies
- Matching emojis
- Many smart reply patterns/templates
- Prayer-specific fun captions
- Content request waiting message
- Better media request handling
- Better automatic daily reminders

Required Render Environment Variables:

BOT_TOKEN
OPENAI_API_KEY
OPENAI_MODEL                  optional

ADSGRAM_BLOCK_ID              bot-52042
ADSGRAM_TOKEN                 REQUIRED for AdsGram Bot API
ADSGRAM_WEBAPP_URL            compatibility

Optional:
TIMEZONE=Asia/Dhaka
PRAYER_CITY=Dhaka
PRAYER_COUNTRY=Bangladesh
PRAYER_METHOD=1
DB_FILE=bot_database.db

AUTO_MESSAGES_ENABLED=true
STUDY_HOURS=7,10,15,19
SPORTS_HOURS=17,21
SLEEP_HOUR=23
WAKE_HOUR=7
WORK_HOURS=9,13,20
"""

import os
import re
import time
import asyncio
import logging
import sqlite3
import traceback
import random
from datetime import datetime
from html import escape as html_escape

import pytz
import aiohttp
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip()

ADMIN_IDS = [8721334265]
ADMIN_USERNAME = "tomalchowdhury2"

# Boss identity
BOSS_NAME = "TOMAL CHOWDHURY"
BOSS_USERNAME = "@tomalchowdhury2"

TIMEZONE_NAME = os.getenv(
    "TIMEZONE",
    "Asia/Dhaka"
)

try:
    TZ = pytz.timezone(TIMEZONE_NAME)
except Exception:
    TZ = pytz.timezone("Asia/Dhaka")

PRAYER_CITY = os.getenv(
    "PRAYER_CITY",
    "Dhaka"
)

PRAYER_COUNTRY = os.getenv(
    "PRAYER_COUNTRY",
    "Bangladesh"
)

PRAYER_METHOD = os.getenv(
    "PRAYER_METHOD",
    "1"
)

DB_FILE = os.getenv(
    "DB_FILE",
    "bot_database.db"
)

# ============================================================================
# ADSGRAM
# ============================================================================

ADSGRAM_BLOCK_ID = os.getenv(
    "ADSGRAM_BLOCK_ID",
    ""
).strip()

ADSGRAM_TOKEN = os.getenv(
    "ADSGRAM_TOKEN",
    ""
).strip()

ADSGRAM_WEBAPP_URL = os.getenv(
    "ADSGRAM_WEBAPP_URL",
    "https://sad.adsgram.ai/js/sad.js"
).strip()

ADSGRAM_ENABLED = bool(
    ADSGRAM_BLOCK_ID and ADSGRAM_TOKEN
)


def adsgram_numeric_block_id():

    value = ADSGRAM_BLOCK_ID.strip()

    if value.lower().startswith("bot-"):
        value = value[4:]

    match = re.search(
        r"\d+",
        value
    )

    if match:
        return match.group(0)

    return value


ADSGRAM_NUMERIC_BLOCK_ID = (
    adsgram_numeric_block_id()
)

# ============================================================================
# AUTOMATIC NOTIFICATIONS
# ============================================================================

AUTO_MESSAGES_ENABLED = os.getenv(
    "AUTO_MESSAGES_ENABLED",
    "true"
).lower() in {
    "1",
    "true",
    "yes",
    "on"
}


def parse_hours(
    value,
    default
):

    result = []

    for item in (
        value.split(",")
        if value
        else []
    ):

        try:

            h = int(
                item.strip()
            )

            if 0 <= h <= 23:
                result.append(h)

        except ValueError:
            pass

    return sorted(
        set(result)
    ) or default


STUDY_HOURS = parse_hours(
    os.getenv(
        "STUDY_HOURS",
        "7,10,15,19"
    ),
    [7, 10, 15, 19]
)

SPORTS_HOURS = parse_hours(
    os.getenv(
        "SPORTS_HOURS",
        "17,21"
    ),
    [17, 21]
)

WORK_HOURS = parse_hours(
    os.getenv(
        "WORK_HOURS",
        "9,13,20"
    ),
    [9, 13, 20]
)

try:
    SLEEP_HOUR = int(
        os.getenv(
            "SLEEP_HOUR",
            "23"
        )
    )
except Exception:
    SLEEP_HOUR = 23

try:
    WAKE_HOUR = int(
        os.getenv(
            "WAKE_HOUR",
            "7"
        )
    )
except Exception:
    WAKE_HOUR = 7

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(
    "telegram_bot"
)

# ============================================================================
# OPENAI
# ============================================================================

openai_client = None

if OPENAI_API_KEY:

    try:

        from openai import AsyncOpenAI

        openai_client = AsyncOpenAI(
            api_key=OPENAI_API_KEY
        )

        logger.info(
            "OpenAI client configured successfully."
        )

    except Exception as e:

        logger.warning(
            "Could not initialize OpenAI client: %s",
            e
        )

else:

    logger.warning(
        "OPENAI_API_KEY is missing."
    )

# ============================================================================
# DATABASE
# ============================================================================


def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def db_execute(
    query,
    params=(),
    fetchone=False,
    fetch=False,
    commit=True
):

    with get_db() as conn:

        cur = conn.cursor()

        cur.execute(
            query,
            params
        )

        if commit:
            conn.commit()

        if fetchone:

            row = cur.fetchone()

            return (
                dict(row)
                if row
                else None
            )

        if fetch:

            return [
                dict(r)
                for r in cur.fetchall()
            ]

        return cur.lastrowid


def now_str():

    return datetime.now(
        TZ
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def init_db():

    with get_db() as conn:

        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            joined_at TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            title TEXT,
            username TEXT,
            created_at TEXT,
            notification_enabled INTEGER DEFAULT 1
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            media_type TEXT NOT NULL,
            file_id TEXT NOT NULL,
            category TEXT DEFAULT 'other',
            views INTEGER DEFAULT 0,
            added_by INTEGER,
            created_at TEXT
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
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            aliases TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """)

        cur.execute(
            "PRAGMA table_info(contents)"
        )

        content_cols = [
            c[1]
            for c in cur.fetchall()
        ]

        if "views" not in content_cols:

            cur.execute(
                "ALTER TABLE contents "
                "ADD COLUMN views INTEGER DEFAULT 0"
            )

        cur.execute(
            "PRAGMA table_info(chats)"
        )

        chat_cols = [
            c[1]
            for c in cur.fetchall()
        ]

        if "notification_enabled" not in chat_cols:

            cur.execute(
                "ALTER TABLE chats "
                "ADD COLUMN notification_enabled "
                "INTEGER DEFAULT 1"
            )

        conn.commit()

    seed_default_categories()

    logger.info(
        "Database initialized."
    )


def save_user(user):

    if not user:
        return

    db_execute(
        """
        INSERT INTO users(
            user_id,
            first_name,
            last_name,
            username,
            joined_at
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            username=excluded.username
        """,
        (
            user.id,
            user.first_name or "",
            user.last_name or "",
            user.username or "",
            now_str(),
        )
    )


def save_chat(chat):

    if not chat:
        return

    db_execute(
        """
        INSERT INTO chats(
            chat_id,
            chat_type,
            title,
            username,
            created_at,
            notification_enabled
        )
        VALUES (?, ?, ?, ?, ?, 1)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            chat_type=excluded.chat_type,
            title=excluded.title,
            username=excluded.username
        """,
        (
            chat.id,
            chat.type,
            chat.title or "",
            chat.username or "",
            now_str(),
        )
    )


def set_chat_notifications(
    chat_id,
    enabled
):

    db_execute(
        """
        UPDATE chats
        SET notification_enabled=?
        WHERE chat_id=?
        """,
        (
            1 if enabled else 0,
            chat_id,
        )
    )


def get_notification_chats():

    return db_execute(
        """
        SELECT
            chat_id,
            chat_type,
            title
        FROM chats
        WHERE notification_enabled=1
        ORDER BY chat_id
        """,
        fetch=True
    )


def save_message(
    chat_id,
    user_id,
    role,
    content
):

    db_execute(
        """
        INSERT INTO messages(
            chat_id,
            user_id,
            role,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            role,
            content,
            now_str(),
        )
    )


def get_history(
    chat_id,
    limit=6
):

    rows = db_execute(
        """
        SELECT role, content
        FROM messages
        WHERE chat_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            chat_id,
            limit
        ),
        fetch=True
    )

    return (
        rows[::-1]
        if rows
        else []
    )


def get_state(key):

    row = db_execute(
        """
        SELECT value
        FROM bot_state
        WHERE key=?
        """,
        (key,),
        fetchone=True
    )

    return (
        row["value"]
        if row
        else None
    )


def set_state(
    key,
    value
):

    db_execute(
        """
        INSERT INTO bot_state(
            key,
            value
        )
        VALUES (?, ?)

        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value
        """,
        (
            key,
            str(value),
        )
    )

# ============================================================================
# DEFAULT CATEGORIES
# ============================================================================

DEFAULT_CATEGORIES = [

    ("romantic", "❤️ রোমান্টিক", "রোমান্টিক,romantic,প্রেমের"),
    ("comedy", "😂 কমেডি", "কমেডি,comedy,হাসির"),
    ("family", "👨‍👩‍👧 ফ্যামিলি", "ফ্যামিলি,family,পারিবারিক"),
    ("emotional", "😭 ইমোশনাল", "ইমোশনাল,emotional"),
    ("love", "💖 ভালোবাসা", "ভালোবাসা,love"),
    ("sad", "💔 দুঃখের", "দুঃখের,sad,দুঃখ"),
    ("action", "💥 অ্যাকশন", "অ্যাকশন,action"),
    ("thriller", "🕵️ থ্রিলার", "থ্রিলার,thriller"),
    ("horror", "👻 ভৌতিক", "ভৌতিক,horror,ভূতের"),
    ("mystery", "🔍 রহস্য", "রহস্য,mystery"),
    ("adventure", "🏕️ অ্যাডভেঞ্চার", "অ্যাডভেঞ্চার,adventure"),
    ("family_drama", "🏠 পারিবারিক নাটক", "পারিবারিক নাটক"),
    ("village", "🌾 গ্রামের গল্প", "গ্রামের গল্প,গ্রাম,গ্রাম্য"),
    ("city", "🏙️ শহরের গল্প", "শহরের গল্প,শহর"),
    ("school", "🏫 স্কুল জীবন", "স্কুল,school,স্কুল জীবন"),
    ("college", "🎓 কলেজ জীবন", "কলেজ,college,কলেজ জীবন"),
    ("office", "💼 অফিস/কাজ", "অফিস,office,কাজের"),
    ("friendship", "🤝 বন্ধুত্ব", "বন্ধুত্ব,friendship"),
    ("couple", "💑 কাপল", "কাপল,couple"),
    ("breakup", "💔 ব্রেকআপ", "ব্রেকআপ,breakup"),
    ("marriage", "💍 বিয়ে", "বিয়ে,বিবাহ,marriage"),
    ("social", "🌍 সামাজিক", "সামাজিক,social"),
    ("islamic", "🕌 ইসলামিক", "ইসলামিক,islamic"),
    ("motivational", "🔥 মোটিভেশনাল", "মোটিভেশনাল,motivational"),
    ("educational", "📚 শিক্ষামূলক", "শিক্ষামূলক,educational"),
    ("funny", "🤣 হাসির", "হাসির,funny"),
    ("viral", "🚀 ভাইরাল", "ভাইরাল,viral"),
    ("trending", "🔥 ট্রেন্ডিং", "ট্রেন্ডিং,trending"),
    ("short", "⚡ শর্ট ভিডিও", "শর্ট,short,শর্ট ভিডিও"),
    ("tiktok", "📱 TikTok", "tiktok,TikTok"),
    ("reels", "🎞️ Reels", "reels,Reels"),
    ("youtube", "▶️ YouTube", "youtube,YouTube"),
    ("movie", "🎬 মুভি", "মুভি,movie,সিনেমা"),
    ("webseries", "📺 ওয়েব সিরিজ", "ওয়েব সিরিজ,webseries,series"),
    ("natok", "🎭 বাংলা নাটক", "নাটক,natok,drama,বাংলা নাটক"),
    ("music", "🎵 গান", "গান,music,song"),
    ("romantic_song", "🎶 রোমান্টিক গান", "রোমান্টিক গান"),
    ("sad_song", "🎼 স্যাড গান", "স্যাড গান"),
    ("folk", "🪕 লোকগান", "লোকগান,folk"),
    ("islamic_song", "🕋 ইসলামিক গান", "ইসলামিক গান"),
    ("gazal", "🎤 গজল", "গজল,gazal"),
    ("nasheed", "🕌 নাশিদ", "নাশিদ,nasheed"),
    ("quran", "📖 কুরআন", "কুরআন,quran"),
    ("waz", "🎙️ ওয়াজ", "ওয়াজ,waz"),
    ("dua", "🤲 দোয়া", "দোয়া,dua"),
    ("hadith", "📜 হাদিস", "হাদিস,hadith"),
    ("ramadan", "🌙 রমজান", "রমজান,ramadan"),
    ("eid", "🌙 ঈদ", "ঈদ,eid"),
    ("dance", "💃 ডান্স", "ডান্স,dance"),
    ("sports", "🏆 স্পোর্টস", "স্পোর্টস,sports"),
    ("cricket", "🏏 ক্রিকেট", "ক্রিকেট,cricket"),
    ("football", "⚽ ফুটবল", "ফুটবল,football"),
    ("wrestling", "🤼 রেসলিং", "রেসলিং,wrestling"),
    ("badminton", "🏸 ব্যাডমিন্টন", "ব্যাডমিন্টন,badminton"),
    ("tennis", "🎾 টেনিস", "টেনিস,tennis"),
    ("basketball", "🏀 বাস্কেটবল", "বাস্কেটবল,basketball"),
    ("volleyball", "🏐 ভলিবল", "ভলিবল,volleyball"),
    ("news", "📰 নিউজ", "নিউজ,news"),
    ("technology", "💻 টেকনোলজি", "টেক,technology,tech"),
    ("ai", "🤖 AI", "ai,এআই"),
    ("programming", "👨‍💻 প্রোগ্রামিং", "প্রোগ্রামিং,programming,coding"),
    ("gaming", "🎮 গেমিং", "গেমিং,gaming"),
    ("mobile_games", "📱 মোবাইল গেম", "মোবাইল গেম"),
    ("pc_games", "🖥️ PC গেম", "pc game,কম্পিউটার গেম"),
    ("travel", "✈️ ভ্রমণ", "ভ্রমণ,travel"),
    ("nature", "🌿 প্রকৃতি", "প্রকৃতি,nature"),
    ("rain", "🌧️ বৃষ্টি", "বৃষ্টি,rain"),
    ("winter", "❄️ শীত", "শীত,winter,শীতের"),
    ("summer", "☀️ গরম", "গরম,summer,hot,heat"),
    ("storm", "⛈️ ঝড়", "ঝড়,storm"),
    ("food", "🍔 খাবার", "খাবার,food"),
    ("cooking", "👨‍🍳 রান্না", "রান্না,cooking"),
    ("recipe", "🍳 রেসিপি", "রেসিপি,recipe"),
    ("street_food", "🌮 স্ট্রিট ফুড", "স্ট্রিট ফুড"),
    ("animals", "🐾 প্রাণী", "প্রাণী,animals"),
    ("pets", "🐶 পোষা প্রাণী", "পোষা প্রাণী,pets"),
    ("kids", "🧒 শিশুদের", "শিশু,kids"),
    ("cartoon", "🧸 কার্টুন", "কার্টুন,cartoon"),
    ("anime", "⚔️ Anime", "anime"),
    ("documentary", "🎥 ডকুমেন্টারি", "ডকুমেন্টারি,documentary"),
    ("history", "🏛️ ইতিহাস", "ইতিহাস,history"),
    ("science", "🔬 বিজ্ঞান", "বিজ্ঞান,science"),
    ("space", "🚀 মহাকাশ", "মহাকাশ,space"),
    ("health", "🩺 স্বাস্থ্য", "স্বাস্থ্য,health"),
    ("fitness", "💪 ফিটনেস", "ফিটনেস,fitness"),
    ("lifestyle", "✨ লাইফস্টাইল", "লাইফস্টাইল,lifestyle"),
    ("fashion", "👕 ফ্যাশন", "ফ্যাশন,fashion"),
    ("beauty", "💄 বিউটি", "বিউটি,beauty"),
    ("cars", "🚗 গাড়ি", "গাড়ি,cars"),
    ("bikes", "🏍️ বাইক", "বাইক,bikes"),
    ("motivation", "🔥 অনুপ্রেরণা", "অনুপ্রেরণা,motivation"),
    ("quotes", "💬 উক্তি", "উক্তি,quotes"),
    ("poetry", "📝 কবিতা", "কবিতা,poetry"),
    ("story", "📖 গল্প", "গল্প,story"),
    ("jokes", "🤣 জোকস", "জোকস,jokes"),
    ("memes", "😂 মিম", "মিম,memes"),
    ("status", "💫 স্ট্যাটাস", "স্ট্যাটাস,status"),
    ("romantic_status", "💞 প্রেমের স্ট্যাটাস", "প্রেমের স্ট্যাটাস"),
    ("sad_status", "💔 স্যাড স্ট্যাটাস", "স্যাড স্ট্যাটাস"),
    ("funny_status", "😂 ফানি স্ট্যাটাস", "ফানি স্ট্যাটাস"),
    ("love_story", "💖 প্রেমের গল্প", "প্রেমের গল্প"),
    ("school_story", "🏫 স্কুলের গল্প", "স্কুলের গল্প"),
    ("village_story", "🌾 গ্রামের গল্প", "গ্রামের গল্প"),
    ("ghost_story", "👻 ভূতের গল্প", "ভূতের গল্প"),
    ("crime", "🔎 ক্রাইম", "ক্রাইম,crime"),
    ("detective", "🕵️ গোয়েন্দা", "গোয়েন্দা,detective"),
    ("political", "🏛️ রাজনৈতিক", "রাজনৈতিক,political"),
    ("business", "💰 ব্যবসা", "ব্যবসা,business"),
    ("earning", "💵 আয়", "আয়,earning"),
    ("freelancing", "💻 ফ্রিল্যান্সিং", "ফ্রিল্যান্সিং,freelancing"),
    ("jobs", "💼 চাকরি", "চাকরি,jobs"),
    ("study", "📚 পড়াশোনা", "পড়াশোনা,study"),
    ("exam", "📝 পরীক্ষা", "পরীক্ষা,exam"),
    ("english", "🇬🇧 ইংরেজি", "ইংরেজি,english"),
    ("bangla", "🇧🇩 বাংলা", "বাংলা,bangla"),
    ("language", "🗣️ ভাষা", "ভাষা,language"),
    ("photography", "📷 ফটোগ্রাফি", "ফটোগ্রাফি,photography"),
    ("cinematic", "🎞️ সিনেমাটিক", "সিনেমাটিক,cinematic"),
    ("editing", "✂️ এডিটিং", "এডিটিং,editing"),
    ("creator", "🎥 ক্রিয়েটর", "ক্রিয়েটর,creator"),
    ("youtube_tips", "▶️ YouTube Tips", "youtube tips"),
    ("telegram", "✈️ Telegram", "telegram"),
    ("apps", "📱 Apps", "অ্যাপ,apps"),
    ("internet", "🌐 Internet", "ইন্টারনেট,internet"),
    ("other", "📂 অন্যান্য", "অন্যান্য,other"),
]


def seed_default_categories():

    count_row = db_execute(
        "SELECT COUNT(*) AS c FROM categories",
        fetchone=True
    )

    count = (
        count_row["c"]
        if count_row
        else 0
    )

    # Important:
    # Existing database categories are NEVER deleted.
    if count > 0:
        return

    for index, item in enumerate(
        DEFAULT_CATEGORIES
    ):

        key, label, aliases = item

        db_execute(
            """
            INSERT OR IGNORE INTO categories(
                key,
                label,
                aliases,
                sort_order,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                key,
                label,
                aliases,
                index,
                now_str(),
            )
        )


def get_categories(
    active_only=True
):

    if active_only:

        return db_execute(
            """
            SELECT *
            FROM categories
            WHERE active=1
            ORDER BY sort_order ASC, key ASC
            """,
            fetch=True
        )

    return db_execute(
        """
        SELECT *
        FROM categories
        ORDER BY sort_order ASC, key ASC
        """,
        fetch=True
    )


def get_category(key):

    return db_execute(
        """
        SELECT *
        FROM categories
        WHERE key=?
        """,
        (key,),
        fetchone=True
    )


def category_exists(key):

    return bool(
        get_category(key)
    )


def get_category_labels():

    rows = get_categories()

    return {
        row["key"]: row["label"]
        for row in rows
    }

# ============================================================================
# TEXT HELPERS
# ============================================================================


def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower()

    text = re.sub(
        r"[^\w\s\u0980-\u09FF]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_category_key(value):

    value = normalize_text(
        value
    )

    value = re.sub(
        r"\s+",
        "_",
        value
    )

    value = re.sub(
        r"[^a-z0-9_\u0980-\u09FF]",
        "",
        value
    )

    return value[:50]

# ============================================================================
# CATEGORY INTENT
# ============================================================================


def category_alias_map():

    result = {}

    rows = get_categories()

    for row in rows:

        key = row["key"]

        result[
            normalize_text(key)
        ] = key

        label_clean = normalize_text(
            row["label"]
        )

        if label_clean:

            result[
                label_clean
            ] = key

        aliases = row["aliases"] or ""

        for alias in aliases.split(","):

            alias = normalize_text(
                alias
            )

            if alias:

                result[
                    alias
                ] = key

    # Direct aliases
    result.update({
        "নাটক": "natok",
        "নাটক দেন": "natok",
        "নাটক দাও": "natok",
        "drama": "natok",
        "natok": "natok",

        "গান": "music",
        "গান দেন": "music",
        "গান দাও": "music",
        "song": "music",
        "music": "music",

        "ভিডিও": "other",
        "ভিডিও দেন": "other",
        "ভিডিও দাও": "other",
        "video": "other",

        "মুভি": "movie",
        "movie": "movie",

        "শীত": "winter",
        "শীতের": "winter",
        "শীতের ভিডিও": "winter",

        "বৃষ্টি": "rain",
        "বৃষ্টি ভিডিও": "rain",

        "গরম": "summer",

        "ক্রিকেট": "cricket",
        "ফুটবল": "football",
        "স্পোর্টস": "sports",

        "ইসলামিক": "islamic",
        "গজল": "gazal",
        "ওয়াজ": "waz",

        "ভাইরাল": "viral",
        "ট্রেন্ডিং": "trending",

        "কার্টুন": "cartoon",
        "গেম": "gaming",
        "গেমিং": "gaming",

        "ভ্রমণ": "travel",
        "প্রকৃতি": "nature",
        "খাবার": "food",
        "রান্না": "cooking",
    })

    return result


def detect_category_intent(text):

    norm = normalize_text(
        text
    )

    if not norm:
        return None

    aliases = category_alias_map()

    if norm in aliases:

        return aliases[norm]

    candidates = sorted(
        aliases.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )

    for alias, key in candidates:

        if len(alias) < 2:
            continue

        if re.search(
            r"(^|\s)"
            + re.escape(alias)
            + r"($|\s)",
            norm
        ):
            return key

    for alias, key in candidates:

        if (
            len(alias) >= 3
            and alias in norm
        ):
            return key

    return None


def is_category_request(text):

    norm = normalize_text(
        text
    )

    category = detect_category_intent(
        norm
    )

    if not category:
        return False

    request_words = [
        "আছে",
        "দাও",
        "দেন",
        "চাই",
        "লাগবে",
        "পাঠাও",
        "পাঠান",
        "দেও",
        "দিবে",
        "দিবেন",
        "দেখাও",
        "দেখান",
        "দেখতে",
        "কি আছে",
        "কিছু আছে",
        "ভিডিও",
        "কন্টেন্ট",
        "content",
        "show",
        "give",
        "please",
    ]

    if any(
        word in norm
        for word in request_words
    ):
        return True

    category_row = get_category(
        category
    )

    return bool(category_row)

# ============================================================================
# CATEGORY BUTTONS
# ============================================================================

CATEGORY_PAGE_SIZE = 12


def category_buttons(
    page=0,
    prefix="usercat"
):

    categories = get_categories()

    total_pages = max(
        1,
        (
            len(categories)
            + CATEGORY_PAGE_SIZE
            - 1
        )
        // CATEGORY_PAGE_SIZE
    )

    page = max(
        0,
        min(
            page,
            total_pages - 1
        )
    )

    start = (
        page * CATEGORY_PAGE_SIZE
    )

    items = categories[
        start:
        start + CATEGORY_PAGE_SIZE
    ]

    buttons = []

    for i in range(
        0,
        len(items),
        2
    ):

        row = []

        for item in items[
            i:i + 2
        ]:

            row.append(
                InlineKeyboardButton(
                    item["label"],
                    callback_data=(
                        f"{prefix}:"
                        f"{item['key']}"
                    )
                )
            )

        buttons.append(row)

    nav = []

    if page > 0:

        nav.append(
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=(
                    f"{prefix}_page:"
                    f"{page - 1}"
                )
            )
        )

    if page < total_pages - 1:

        nav.append(
            InlineKeyboardButton(
                "🔽 See More",
                callback_data=(
                    f"{prefix}_page:"
                    f"{page + 1}"
                )
            )
        )

    if nav:
        buttons.append(nav)

    return (
        buttons,
        page,
        total_pages
    )


def category_prompt(
    prefix="usercat",
    page=0,
    heading="📂 Category"
):

    buttons, page, total_pages = (
        category_buttons(
            page,
            prefix
        )
    )

    total = len(
        get_categories()
    )

    if prefix == "usercat":

        text = (
            f"{heading}\n\n"
            "অবশ্যই! 👇\n"
            "আপনার প্রয়োজনীয় Category "
            "নির্বাচন করুন।\n\n"
            f"📂 মোট Category: {total}\n"
            f"📄 Page {page + 1}/{total_pages}"
        )

    else:

        text = (
            "🏷️ Category নির্বাচন করুন\n\n"
            "ভিডিওটি কোন Category-তে রাখতে "
            "চান সেটি নির্বাচন করুন। 👇\n\n"
            f"📂 মোট Category: {total}\n"
            f"📄 Page {page + 1}/{total_pages}"
        )

    return (
        text,
        InlineKeyboardMarkup(
            buttons
        )
    )

# ============================================================================
# CONTENT
# ============================================================================


def detect_category(title):

    t = normalize_text(
        title
    )

    if any(
        x in t
        for x in [
            "নাটক",
            "drama",
            "natok"
        ]
    ):
        return "natok"

    if any(
        x in t
        for x in [
            "গান",
            "song",
            "audio",
            "গজল",
            "music"
        ]
    ):
        return "music"

    if any(
        x in t
        for x in [
            "মুভি",
            "movie",
            "cinema",
            "ফিল্ম"
        ]
    ):
        return "movie"

    if any(
        x in t
        for x in [
            "ডান্স",
            "dance"
        ]
    ):
        return "dance"

    if any(
        x in t
        for x in [
            "শীত",
            "winter"
        ]
    ):
        return "winter"

    if any(
        x in t
        for x in [
            "বৃষ্টি",
            "rain"
        ]
    ):
        return "rain"

    if any(
        x in t
        for x in [
            "গরম",
            "summer",
            "hot"
        ]
    ):
        return "summer"

    return "other"


def search_content(
    query,
    category=None
):

    query = normalize_text(
        query
    )

    if not query:
        return None

    if category:

        row = db_execute(
            """
            SELECT *
            FROM contents
            WHERE category=?
            AND lower(title) LIKE ?
            ORDER BY views DESC, id DESC
            LIMIT 1
            """,
            (
                category,
                f"%{query}%"
            ),
            fetchone=True
        )

        if row:
            return row

    row = db_execute(
        """
        SELECT *
        FROM contents
        WHERE lower(title) LIKE ?
        ORDER BY views DESC, id DESC
        LIMIT 1
        """,
        (
            f"%{query}%",
        ),
        fetchone=True
    )

    if row:
        return row

    words = [
        w
        for w in query.split()
        if len(w) >= 2
    ][:5]

    if not words:
        return None

    conditions = [
        "lower(title) LIKE ?"
        for _ in words
    ]

    params = [
        f"%{w}%"
        for w in words
    ]

    if category:

        sql = (
            "SELECT * FROM contents "
            "WHERE category=? AND ("
            + " OR ".join(
                conditions
            )
            + ") "
            "ORDER BY views DESC,id DESC "
            "LIMIT 1"
        )

        return db_execute(
            sql,
            (
                category,
                *params
            ),
            fetchone=True
        )

    sql = (
        "SELECT * FROM contents "
        "WHERE ("
        + " OR ".join(
            conditions
        )
        + ") "
        "ORDER BY views DESC,id DESC "
        "LIMIT 1"
    )

    return db_execute(
        sql,
        tuple(params),
        fetchone=True
    )


def increment_views(
    content_id
):

    db_execute(
        """
        UPDATE contents
        SET views=views+1
        WHERE id=?
        """,
        (content_id,)
    )


def get_contents_by_category(
    category,
    limit=5
):

    return db_execute(
        """
        SELECT
            id,
            title,
            media_type,
            category,
            views
        FROM contents
        WHERE category=?
        ORDER BY views DESC,id DESC
        LIMIT ?
        """,
        (
            category,
            limit
        ),
        fetch=True
    )


def get_top_trending(
    limit=5
):

    return db_execute(
        """
        SELECT
            id,
            title,
            media_type,
            category,
            views
        FROM contents
        ORDER BY views DESC,id DESC
        LIMIT ?
        """,
        (limit,),
        fetch=True
    )


async def show_category_content(
    message,
    category_key,
    send_waiting=True
):

    category = get_category(
        category_key
    )

    if not category:

        await message.reply_text(
            "❌ এই Category পাওয়া যায়নি।"
        )

        return

    # User specifically requested this behavior.
    if send_waiting:

        await message.reply_text(
            "অবশ্যই একটু অপেক্ষা করুন দিচ্ছি.. ⏳😊"
        )

    items = get_contents_by_category(
        category_key,
        10
    )

    if not items:

        await message.reply_text(
            "😔 এই Category-তে এখনো কোনো "
            "কন্টেন্ট যোগ করা হয়নি।\n\n"
            f"📂 Category: {category['label']}\n\n"
            "নতুন কন্টেন্ট এলে এখানেই পাওয়া যাবে।"
        )

        return

    buttons = []

    for item in items:

        title = str(
            item["title"]
        )[:55]

        buttons.append([
            InlineKeyboardButton(
                f"🎬 {title}",
                callback_data=(
                    f"send_media_{item['id']}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ Category List",
            callback_data="usercat_page:0"
        )
    ])

    await message.reply_text(
        f"📂 {category['label']}\n\n"
        "নিচের কন্টেন্ট থেকে যেটি চান "
        "সেটি নির্বাচন করুন। 👇",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )

# ============================================================================
# OPENAI
# ============================================================================


SYSTEM_INSTRUCTIONS = f"""
তুমি একটি দ্রুত, বন্ধুসুলভ Telegram AI সহকারী।

তোমার Boss:
{BOSS_NAME}
Username:
{BOSS_USERNAME}

Admin ID:
{ADMIN_IDS[0]}

নিয়ম:

1. ব্যবহারকারী বাংলায় লিখলে বাংলায় উত্তর দেবে।
2. Banglish হলে সহজ বাংলা/Banglish বুঝে উত্তর দেবে।
3. English হলে English-এ উত্তর দেবে।
4. সংক্ষিপ্ত এবং সরাসরি উত্তর দেবে।
5. Bot database-এ থাকা মিডিয়া ছাড়া কোনো মিডিয়া আছে বলে দাবি করবে না।
6. Category system-এর কাজ local bot code করবে।
7. নিজের পরিচয় চাইলে বলবে:
   "আমার Boss, TOMAL CHOWDHURY আমাকে তৈরি করছে।
   Boss username: @tomalchowdhury2"
8. Bot কোথায় থাকে জিজ্ঞেস করলে বলবে:
   "আমার কোনো বাসা নেই, আমি আমার user name,
   TOMAL CHOWDHURY বসের সাথে থাকি এবং বসের কথা শুনি।
   Boss: @tomalchowdhury2"
9. Admin সম্পর্কে:
   @{ADMIN_USERNAME}
"""


async def generate_chatgpt_response(
    chat_id,
    user_text
):

    history = get_history(
        chat_id,
        limit=6
    )

    if (
        not openai_client
        or not OPENAI_API_KEY
    ):

        return (
            "👋 আপনার বার্তা পেয়েছি!\n\n"
            "AI উত্তর দেওয়ার জন্য OpenAI API Key "
            "সঠিকভাবে সেট করা হয়নি।\n\n"
            f"প্রয়োজনে @{ADMIN_USERNAME}-এর "
            "সাথে যোগাযোগ করুন।"
        )

    try:

        inputs = []

        for h in history:

            inputs.append({
                "role": (
                    "assistant"
                    if h["role"] == "assistant"
                    else "user"
                ),
                "content": h["content"]
            })

        inputs.append({
            "role": "user",
            "content": user_text
        })

        response = await asyncio.wait_for(
            openai_client.responses.create(
                model=OPENAI_MODEL,
                instructions=SYSTEM_INSTRUCTIONS,
                input=inputs,
                max_output_tokens=500,
            ),
            timeout=15.0
        )

        answer = getattr(
            response,
            "output_text",
            None
        )

        if answer and answer.strip():

            return answer.strip()

    except asyncio.TimeoutError:

        logger.error(
            "OpenAI request timed out."
        )

    except Exception as e:

        logger.error(
            "OpenAI AI error: %r",
            e
        )

    return (
        "দুঃখিত, এখন AI উত্তর দিতে একটু সমস্যা হচ্ছে। "
        "কিছুক্ষণ পর আবার চেষ্টা করুন। 🙏"
    )

# ============================================================================
# ADSGRAM
# ============================================================================


async def get_adsgram_ad(
    user_id
):

    if not ADSGRAM_ENABLED:

        logger.warning(
            "AdsGram disabled: BLOCK_ID or TOKEN missing."
        )

        return None

    if not ADSGRAM_NUMERIC_BLOCK_ID:

        logger.warning(
            "AdsGram block ID is invalid."
        )

        return None

    url = (
        "https://api.adsgram.ai/advbot"
        f"?tgid={user_id}"
        f"&blockid={ADSGRAM_NUMERIC_BLOCK_ID}"
        "&language=bn"
        f"&token={ADSGRAM_TOKEN}"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=8
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url
            ) as response:

                if response.status != 200:

                    logger.warning(
                        "AdsGram returned HTTP %s",
                        response.status
                    )

                    return None

                data = await response.json(
                    content_type=None
                )

                if not isinstance(
                    data,
                    dict
                ):
                    return None

                return data

    except Exception as e:

        logger.warning(
            "AdsGram request failed: %r",
            e
        )

        return None


async def send_adsgram_ad(
    bot,
    chat_id,
    user_id
):

    data = await get_adsgram_ad(
        user_id
    )

    if not data:
        return False

    text_html = data.get(
        "text_html",
        ""
    )

    image_url = data.get(
        "image_url"
    )

    click_url = data.get(
        "click_url"
    )

    button_name = data.get(
        "button_name"
    )

    reward_url = data.get(
        "reward_url"
    )

    button_reward_name = data.get(
        "button_reward_name"
    )

    buttons = []

    if click_url and button_name:

        buttons.append([
            InlineKeyboardButton(
                str(button_name)[:64],
                url=click_url
            )
        ])

    if (
        reward_url
        and button_reward_name
    ):

        buttons.append([
            InlineKeyboardButton(
                str(button_reward_name)[:64],
                url=reward_url
            )
        ])

    reply_markup = (
        InlineKeyboardMarkup(buttons)
        if buttons
        else None
    )

    if not text_html:

        text_html = (
            "📢 Advertisement"
        )

    try:

        if image_url:

            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=text_html[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                protect_content=True,
            )

        else:

            await bot.send_message(
                chat_id=chat_id,
                text=text_html[:4096],
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                protect_content=True,
            )

        return True

    except Exception as e:

        logger.warning(
            "Could not send AdsGram ad: %r",
            e
        )

        return False

# ============================================================================
# ADMIN NOTIFICATIONS
# ============================================================================


def safe_markdown(text):

    if not text:
        return ""

    return str(text).replace(
        "`",
        "'"
    )


async def send_admin_alert(
    bot,
    text,
    reply_markup=None
):

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )

        except Exception as e:

            logger.error(
                "Failed to notify admin %s: %s",
                admin_id,
                e
            )


async def notify_admin_missing_content(
    bot,
    user,
    content_type,
    query
):

    text = (
        "📢 **[নতুন কন্টেন্টের ডিমান্ড]**\n\n"
        f"👤 **ইউজার:** "
        f"{safe_markdown(user.first_name)} "
        f"(@{user.username or 'নাই'})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📁 **Category:** {content_type}\n"
        f"🔍 **রিকুয়েস্ট:** "
        f"`{safe_markdown(query)}`\n"
        f"⏰ **সময়:** {now_str()}\n\n"
        f"👉 @{ADMIN_USERNAME} "
        "কন্টেন্টটি আপলোড করতে পারেন।"
    )

    keyboard = None

    if user.username:

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"✉️ Reply @{user.username}",
                    url=(
                        f"https://t.me/"
                        f"{user.username}"
                    )
                )
            ]
        ])

    await send_admin_alert(
        bot,
        text,
        keyboard
    )


async def notify_admin_user_help(
    bot,
    user,
    user_msg
):

    text = (
        "⚠️ **[ইউজার সাহায্য চেয়েছে]**\n\n"
        f"👤 **User:** "
        f"{safe_markdown(user.first_name)} "
        f"(@{user.username or 'N/A'})\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"⏰ **Time:** {now_str()}\n\n"
        f"💬 **বার্তা:**\n"
        f"_{safe_markdown(user_msg)}_"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 সরাসরি মেসেজ দিন",
                url=(
                    f"https://t.me/{user.username}"
                    if user.username
                    else
                    f"tg://user?id={user.id}"
                )
            )
        ]
    ])

    await send_admin_alert(
        bot,
        text,
        keyboard
    )

# ============================================================================
# MEDIA DELIVERY
# ============================================================================


async def deliver_media(
    update,
    row
):

    message = update.effective_message
    user = update.effective_user

    content_id = row["id"]
    media_type = row["media_type"]
    file_id = row["file_id"]
    title = row["title"]

    # Ads first
    if user:

        await send_adsgram_ad(
            update.get_bot(),
            message.chat_id,
            user.id
        )

    increment_views(
        content_id
    )

    await message.reply_text(
        f"🎬 {title}\n\n"
        "⏳ পাঠানো হচ্ছে, দয়া করে অপেক্ষা করুন..."
    )

    try:

        if media_type == "video":

            await message.reply_video(
                video=file_id,
                caption=f"🎬 {title}",
                supports_streaming=True,
            )

        elif media_type == "audio":

            await message.reply_audio(
                audio=file_id,
                caption=f"🎵 {title}"
            )

        elif media_type == "photo":

            await message.reply_photo(
                photo=file_id,
                caption=f"🖼️ {title}"
            )

        elif media_type == "animation":

            await message.reply_animation(
                animation=file_id,
                caption=f"✨ {title}"
            )

        else:

            await message.reply_document(
                document=file_id,
                caption=f"📄 {title}"
            )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 এডমিন: @"
                    + ADMIN_USERNAME,
                    url=(
                        f"https://t.me/"
                        f"{ADMIN_USERNAME}"
                    )
                )
            ]
        ])

        await message.reply_text(
            "✅ কন্টেন্ট সফলভাবে পাঠানো হয়েছে!\n"
            "আর কোনো নাটক, গান বা ভিডিও লাগলে "
            "নাম লিখুন। 🤝",
            reply_markup=keyboard
        )

    except Exception as e:

        logger.error(
            "Error sending media %s: %r",
            content_id,
            e
        )

        await send_admin_alert(
            update.get_bot(),
            f"❌ Error sending file ID "
            f"{content_id}: {e}"
        )

        await message.reply_text(
            "❌ ফাইলটি পাঠাতে সমস্যা হয়েছে। "
            "এডমিনকে জানানো হয়েছে।"
        )


async def handle_admin_media_upload(
    update,
    context
):

    user = update.effective_user
    message = update.effective_message

    if (
        not user
        or not is_admin(user.id)
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
        "file_id": file_id,
    }

    context.user_data[
        "waiting_title"
    ] = True

    await message.reply_text(
        f"📥 {media_type.upper()} মিডিয়া ফাইল পেয়েছি!\n\n"
        "📝 এই কন্টেন্টের নাম (Title) লিখে পাঠান।\n\n"
        "যেমন:\n"
        "নতুন ঈদের নাটক\n"
        "বাংলা গান"
    )

    return True


async def handle_admin_title_save(
    update,
    context
):

    user = update.effective_user
    message = update.effective_message

    if (
        not user
        or not is_admin(user.id)
        or not context.user_data.get(
            "waiting_title"
        )
    ):
        return False

    title = (
        message.text.strip()
        if message.text
        else ""
    )

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

    context.user_data[
        "pending_title"
    ] = title

    context.user_data[
        "waiting_title"
    ] = False

    context.user_data[
        "waiting_category"
    ] = True

    text, markup = category_prompt(
        prefix="admincat",
        page=0
    )

    await message.reply_text(
        f"✅ নাম গ্রহণ করা হয়েছে:\n"
        f"🎬 {title}\n\n"
        + text,
        reply_markup=markup
    )

    return True

# ============================================================================
# WEATHER / PRAYER
# ============================================================================


async def get_weather():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=23.8103"
        "&longitude=90.4125"
        "&current=temperature_2m,"
        "relative_humidity_2m,"
        "weather_code,"
        "wind_speed_10m"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=6
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url
            ) as res:

                if res.status != 200:
                    return None

                data = await res.json()

        current = data.get(
            "current",
            {}
        )

        return (
            f"🌤️ **{PRAYER_CITY} আবহাওয়া**\n\n"
            f"🌡️ তাপমাত্রা: "
            f"**{current.get('temperature_2m', '?')}°C**\n"
            f"💧 আর্দ্রতা: "
            f"**{current.get('relative_humidity_2m', '?')}%**\n"
            f"💨 বাতাস: "
            f"**{current.get('wind_speed_10m', '?')} km/h**"
        )

    except Exception as e:

        logger.warning(
            "Weather API error: %r",
            e
        )

        return None


_prayer_cache_date = None
_prayer_cache_data = None


async def get_prayer_data():

    global _prayer_cache_date
    global _prayer_cache_data

    today = datetime.now(
        TZ
    ).strftime(
        "%Y-%m-%d"
    )

    if (
        _prayer_cache_date == today
        and _prayer_cache_data
    ):

        return _prayer_cache_data

    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        f"&method={PRAYER_METHOD}"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=8
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(
                url
            ) as res:

                if res.status != 200:
                    return None

                data = await res.json()

        timings = (
            data
            .get("data", {})
            .get("timings", {})
        )

        if timings:

            _prayer_cache_date = today
            _prayer_cache_data = timings

        return timings

    except Exception as e:

        logger.warning(
            "Prayer API error: %r",
            e
        )

        return None


async def get_prayer_times():

    t = await get_prayer_data()

    if not t:
        return None

    return (
        f"🕌 **{PRAYER_CITY} নামাজের সময়সূচি**\n\n"
        f"🌅 ফজর: **{t.get('Fajr', '-')}**\n"
        f"☀️ সূর্যোদয়: {t.get('Sunrise', '-')}\n"
        f"🕛 যোহর: **{t.get('Dhuhr', '-')}**\n"
        f"🌇 আসর: **{t.get('Asr', '-')}**\n"
        f"🌆 মাগরিব: **{t.get('Maghrib', '-')}**\n"
        f"🌙 এশা: **{t.get('Isha', '-')}**"
    )

# ============================================================================
# PRAYER FUN CAPTIONS
# ============================================================================


PRAYER_CAPTIONS = {

    "Fajr": [
        "🌅 ফজরের সময় হয়েছে—ঘুম ভেঙে ওজু করে নামাজ পড়ে নিন। 🤲❤️",
        "🌄 নতুন দিনের শুরু ফজরের নামাজ দিয়ে হোক। সবাই নামাজ পড়ে নিন। 🕌✨",
        "😴 ঘুম আর কত? ফজরের আজান হয়েছে—চলুন নামাজ পড়ে নিই। 🤲",
        "🌅 ফজর এসেছে, আল্লাহর স্মরণে দিনটা শুরু করি। 🕌❤️",
    ],

    "Dhuhr": [
        "☀️ এখন যোহরের সময়—সবাই নামাজ পড়ে নিন। 🕌🤲",
        "🕛 দুপুর হয়েছে, কাজের মাঝে যোহরের নামাজটা পড়ে নিন। ❤️🕌",
        "☀️ ব্যস্ততার মাঝেও নামাজ ভুলবেন না—এখন যোহরের সময়। 🤲",
        "🕌 যোহরের সময় হয়েছে। একটু কাজ থামিয়ে নামাজ পড়ে আসুন। ❤️",
    ],

    "Asr": [
        "🌇 এখন আসরের সময়—সবাই নামাজ পড়ে নিন। 🕌🤲",
        "🏏 খেলাধুলা/কাজ একটু থামিয়ে আসরের নামাজ পড়ে নিন। ❤️",
        "🌤️ বিকেলের সুন্দর সময়ে আসরের নামাজ আদায় করুন। 🕌✨",
        "🤲 আসরের সময় হয়ে গেছে—চলুন নামাজ পড়ে নিই। ❤️",
    ],

    "Maghrib": [
        "🌆 এখন মাগরিবের সময়—সবাই নামাজ পড়ে নিন। 🕌🤲",
        "🌇 সূর্য ডুবে গেছে, মাগরিবের নামাজটা পড়ে নিন। ❤️",
        "🕌 সন্ধ্যার শুরুটা নামাজ দিয়ে করি—মাগরিবের সময় হয়েছে। 🤲✨",
        "🌙 মাগরিবের সময় হয়েছে। আল্লাহর স্মরণে কয়েক মিনিট দিন। ❤️🕌",
    ],

    "Isha": [
        "🌙 এখন এশার সময়—সবাই নামাজ পড়ে নিন। 🕌🤲",
        "😴 ঘুমানোর আগে এশার নামাজটা পড়ে নিন। ❤️",
        "🌙 রাত হয়েছে, এশার নামাজ আদায় করে তারপর বিশ্রাম নিন। 🕌",
        "🤲 দিনের শেষ নামাজ এশা—চলুন নামাজ পড়ে নিই। ❤️✨",
    ],
}


PRAYER_NAMES = {
    "Fajr": "ফজর",
    "Dhuhr": "যোহর",
    "Asr": "আসর",
    "Maghrib": "মাগরিব",
    "Isha": "এশা",
}

# ============================================================================
# HOURLY AUTOMATIC MESSAGE
# ============================================================================


def hourly_message(hour):

    h12 = hour % 12 or 12

    ampm = (
        "AM"
        if hour < 12
        else "PM"
    )

    parts = [
        (
            f"🕐 **সময়: {h12}:00 {ampm} "
            "(বাংলাদেশ সময়)**\n"
        )
    ]

    if hour == WAKE_HOUR:

        parts.append(
            random.choice([
                "🌅 **ঘুম থেকে ওঠার সময়!**\n"
                "সুপ্রভাত! পানি পান করুন এবং দিনটা সুন্দরভাবে শুরু করুন। ☀️💧",

                "🌞 সকাল হয়ে গেছে! ঘুম থেকে উঠে মুখ ধুয়ে পানি পান করুন। 💧😊",

                "🌅 উঠে পড়ুন! আজকের দিনটা নতুন কিছু করার জন্য। 💪✨",
            ])
        )

    if hour in STUDY_HOURS:

        parts.append(
            random.choice([
                "📚 **পড়াশোনার সময়!**\n"
                "এখন মনোযোগ দিয়ে পড়াশোনা বা স্কিল শেখার সময়। 📖🎯",

                "📖 বইটা খুলে বসার সময় হয়েছে। অল্প হলেও আজ পড়ুন। 💪📚",

                "🎓 আজকের পড়াটা আজই শেষ করুন—আগামীকালের জন্য জমিয়ে রাখবেন না। 📚",
            ])
        )

    if hour in SPORTS_HOURS:

        parts.append(
            random.choice([
                "⚽ **খেলার/ব্যায়ামের সময়!**\n"
                "কিছুক্ষণ খেলাধুলা বা শরীরচর্চা করুন। 🏃‍♂️💪",

                "🏏 একটু শরীরচর্চা করুন, শরীর ভালো থাকলে মনও ভালো থাকবে। 💪😊",

                "⚽ খেলাধুলার সময়! ফোনটা নামিয়ে একটু নড়াচড়া করুন। 😄🏃",
            ])
        )

    if hour in WORK_HOURS:

        parts.append(
            random.choice([
                "💼 **কাজের সময়!**\n"
                "গুরুত্বপূর্ণ কাজগুলো গুছিয়ে করুন। ✅",

                "💻 কাজের সময় হয়েছে। আজকের সবচেয়ে জরুরি কাজটা আগে শেষ করুন। 🎯",

                "💼 কাজের মাঝে মনোযোগ রাখুন—একটা একটা করে কাজ শেষ করুন। 💪",
            ])
        )

    if hour == 8:

        parts.append(
            "🍳 সকালবেলার নাশতা করার সময়! শরীরকে না খাইয়ে রাখবেন না। 🥚☕❤️"
        )

    if hour == 12:

        parts.append(
            random.choice([
                "🍚 দুপুর হয়েছে—সময়মতো খাবার খান এবং পানি পান করুন। 💧",

                "🍛 দুপুরের খাবার খেয়ে নিন। খালি পেটে বেশি কাজ করবেন না। 😊",

                "🥗 Lunch time! ভালোভাবে খাবার খান এবং একটু বিশ্রাম নিন। ❤️",
            ])
        )

    if hour == 15:

        parts.append(
            "☕ বিকেলের দিকে একটু পানি/চা খেয়ে শরীরটাকে ফ্রেশ করে নিন। 😊"
        )

    if hour == 18:

        parts.append(
            "🌇 সন্ধ্যা হয়েছে। পরিবারের সাথে কিছু সময় কাটান এবং নামাজের কথা মনে রাখুন। 🕌❤️"
        )

    if hour == 20:

        parts.append(
            "🍽️ রাতের খাবারের সময় কাছাকাছি—সময়মতো খাবার খেয়ে নিন। 😊"
        )

    if hour == SLEEP_HOUR:

        parts.append(
            random.choice([
                "😴 **ঘুমানোর সময়!**\n"
                "সময়মতো ঘুমান এবং শরীর ও মনকে বিশ্রাম দিন। 🌙",

                "🌙 রাত বেশি করবেন না। ফোনটা পাশে রেখে ঘুমিয়ে পড়ুন। 😴❤️",

                "😴 আজকের কাজ শেষ। এখন বিশ্রামের সময়—শুভ রাত্রি। 🌙✨",
            ])
        )

    if hour == 22:

        parts.append(
            "🌙 ঘুমানোর প্রস্তুতি নিন—আগামীকাল ফ্রেশ থাকতে ভালো ঘুম দরকার। 😴"
        )

    if len(parts) == 1:

        parts.append(
            random.choice([
                "✅ আপনার কাজের তালিকা দেখে পরের এক ঘণ্টার লক্ষ্য ঠিক করুন। 🎯",

                "💧 একটু পানি পান করুন এবং নিজের খেয়াল রাখুন। 😊",

                "🌟 সময় চলে যাচ্ছে—আজকের ছোট একটি কাজ এখনই শেষ করে ফেলুন। 💪",

                "🧠 কয়েক মিনিট নিজের জন্য রাখুন। তারপর আবার কাজে ফিরুন। ❤️",
            ])
        )

    return "\n\n".join(
        parts
    )

# ============================================================================
# SEND AUTOMATIC MESSAGE
# ============================================================================


async def send_to_enabled_chats(
    bot,
    text
):

    chats = get_notification_chats()

    sent = 0

    for row in chats:

        try:

            await bot.send_message(
                chat_id=row["chat_id"],
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )

            sent += 1

            await asyncio.sleep(
                0.05
            )

        except Exception as e:

            logger.warning(
                "Auto message failed for chat %s: %s",
                row["chat_id"],
                e
            )

    return sent


async def send_hourly_notification(
    bot,
    now
):

    key = now.strftime(
        "%Y-%m-%d-%H"
    )

    if get_state(
        "last_hourly_notification"
    ) == key:

        return

    set_state(
        "last_hourly_notification",
        key
    )

    text = hourly_message(
        now.hour
    )

    sent = await send_to_enabled_chats(
        bot,
        text
    )

    logger.info(
        "Hourly notification sent to %s chats.",
        sent
    )


async def send_prayer_notifications(
    bot,
    now
):

    timings = await get_prayer_data()

    if not timings:
        return

    today = now.strftime(
        "%Y-%m-%d"
    )

    current_minutes = (
        now.hour * 60
        + now.minute
    )

    for key, label in PRAYER_NAMES.items():

        value = timings.get(
            key,
            ""
        )

        match = re.match(
            r"^(\d{1,2}):(\d{2})",
            str(value)
        )

        if not match:
            continue

        target = (
            int(match.group(1)) * 60
            + int(match.group(2))
        )

        if abs(
            current_minutes - target
        ) <= 1:

            state_key = (
                f"prayer_sent_"
                f"{today}_{key}"
            )

            if get_state(
                state_key
            ) == "1":

                continue

            set_state(
                state_key,
                "1"
            )

            caption = random.choice(
                PRAYER_CAPTIONS.get(
                    key,
                    [
                        f"🕌 এখন {label} নামাজের সময় হয়েছে। সবাই নামাজ পড়ে নিন। 🤲"
                    ]
                )
            )

            text = (
                f"{caption}\n\n"
                f"⏰ সময়: **{value}**"
            )

            sent = await send_to_enabled_chats(
                bot,
                text
            )

            logger.info(
                "Prayer notification %s sent to %s chats.",
                label,
                sent
            )


async def automatic_notification_loop(
    application
):

    logger.info(
        "Automatic notifications started."
    )

    while True:

        try:

            if AUTO_MESSAGES_ENABLED:

                now = datetime.now(
                    TZ
                )

                if now.minute == 0:

                    await send_hourly_notification(
                        application.bot,
                        now
                    )

                await send_prayer_notifications(
                    application.bot,
                    now
                )

            await asyncio.sleep(
                20
            )

        except asyncio.CancelledError:

            logger.info(
                "Automatic notification loop stopped."
            )

            raise

        except Exception as e:

            logger.error(
                "Automatic notification loop error: %r",
                e
            )

            await asyncio.sleep(
                20
            )

# ============================================================================
# FAST SMART REPLY ENGINE
# ============================================================================


SMART_REPLY_RULES = [

    # --------------------------------------------------------
    # Creator
    # --------------------------------------------------------

    (
        [
            "তোমাকে কে তৈরি",
            "তোমাকে কে বানাইছে",
            "তোমাকে কে বানিয়েছে",
            "কে তোমাকে বানিয়েছে",
            "কে বানাইছে তোমাকে",
            "তোমার creator কে",
            "creator কে",
            "who created you",
            "who made you",
            "তোমার বস কে",
            "তোমার boss কে",
            "কে তোমার boss",
        ],
        [
            "🤖 আমাকে আমার Boss, TOMAL CHOWDHURY তৈরি করছে। 👑\n"
            "আমার Boss-এর Username: @tomalchowdhury2 ❤️",

            "😎 আমার Boss হলো TOMAL CHOWDHURY। 👑\n"
            "আমি Boss-এর কথা শুনি। 😄\n"
            "Boss: @tomalchowdhury2",

            "🤖 আমার পেছনে যে মানুষটা কাজ করছে তিনি হলেন "
            "TOMAL CHOWDHURY। 👑🔥\n"
            "Username: @tomalchowdhury2",
        ]
    ),

    # --------------------------------------------------------
    # Home / location
    # --------------------------------------------------------

    (
        [
            "তুমি কোথায় থাকো",
            "তুমি কই থাকো",
            "তোমার বাসা কোথায়",
            "তোমার বাড়ি কোথায়",
            "তোমার home কোথায়",
            "where do you live",
            "where is your home",
            "তুমি কোথায় থাক",
        ],
        [
            "🏠 আমার কোনো বাসা নেই, আমি আমার user name, "
            "TOMAL CHOWDHURY বসের সাথে থাকি এবং বসের কথা শুনি। 😎\n"
            "👑 Boss: @tomalchowdhury2",

            "🤖 আমার নিজের কোনো বাড়ি নেই। 😄\n"
            "আমি আমার Boss TOMAL CHOWDHURY-এর সাথে থাকি "
            "এবং Boss-এর কথা শুনি। 👑\n"
            "@tomalchowdhury2",

            "🏠 আমার ঠিকানা হলো—আমার Boss TOMAL CHOWDHURY-এর "
            "সাথে! 😎👑\n"
            "Boss Username: @tomalchowdhury2",
        ]
    ),

    # --------------------------------------------------------
    # Stop / apology
    # --------------------------------------------------------

    (
        [
            "থামো তুমি",
            "থাম তুমি",
            "চুপ কর",
            "চুপ করো",
            "stop",
            "shut up",
            "থাম",
        ],
        [
            "আচ্ছা আচ্ছা 😅 থেমে গেলাম। 🤐❤️",
            "ওকে Boss 😅🤐 আর বলছি না।",
            "ঠিক আছে 😔🙏 আমি চুপ থাকছি।",
            "আচ্ছা ভাই 😄✋ এখন শান্ত!",
        ]
    ),

    # --------------------------------------------------------
    # Greeting
    # --------------------------------------------------------

    (
        [
            "হ্যালো",
            "হ্যালো ভাই",
            "hello",
            "hi",
            "hey",
            "আসসালামু আলাইকুম",
            "সালাম",
            "কেমন আছ",
            "কেমন আছো",
            "কি খবর",
        ],
        [
            "ওয়ালাইকুম আসসালাম! 😊❤️ কেমন আছেন?",
            "হ্যালো! 👋😊 আমি আছি, আপনার কথা শুনছি।",
            "আলহামদুলিল্লাহ 🤍 আমি ভালো আছি। আপনার কী খবর?",
            "হাই! 😎🔥 বলুন, কী করতে পারি?",
            "ওয়ালাইকুম আসসালাম 🌙❤️ বলুন ভাই, কী লাগবে?",
        ]
    ),

    # --------------------------------------------------------
    # Thanks
    # --------------------------------------------------------

    (
        [
            "ধন্যবাদ",
            "থ্যাংকস",
            "thanks",
            "thank you",
            "অনেক ধন্যবাদ",
        ],
        [
            "স্বাগতম! 😊❤️",
            "আপনাকে স্বাগতম ভাই। 🤝😊",
            "যখন দরকার ডাকবেন। 😎❤️",
            "কোনো সমস্যা নেই! 🤗✨",
        ]
    ),

    # --------------------------------------------------------
    # Rain
    # --------------------------------------------------------

    (
        [
            "আজ বৃষ্টি হচ্ছে",
            "আজকে বৃষ্টি হচ্ছে",
            "বৃষ্টি হচ্ছে",
            "বৃষ্টি নামছে",
            "আজ বৃষ্টি",
            "বৃষ্টি",
            "rain",
        ],
        [
            "🌧️ দারুণ! আজকে প্রিয় মানুষের সাথে বৃষ্টিতে ভিজতে পারলে ভালো লাগতো। ❤️☔",

            "🌧️ আজ বৃষ্টি! ☔ এক কাপ চা আর প্রিয় মানুষের সঙ্গ হলে একদম জমে যেত। ❤️☕",

            "আহা বৃষ্টি! 🌧️☔ আজকের আবহাওয়াটা একদম রোমান্টিক। 😄❤️",

            "🌧️ বৃষ্টি মানেই অন্যরকম একটা অনুভূতি। নিরাপদে থাকুন আর বৃষ্টিটা উপভোগ করুন। ☔😊",

            "আজ আকাশও মনে হয় প্রেমে পড়েছে! 😂🌧️❤️",
        ]
    ),

    # --------------------------------------------------------
    # Heat
    # --------------------------------------------------------

    (
        [
            "আজ অনেক গরম",
            "আজকে অনেক গরম",
            "অনেক গরম",
            "গরম প্রচুর",
            "আজ গরম",
            "গরম লাগছে",
            "গরম লাগতেছে",
            "খুব গরম",
            "hot",
            "heat",
        ],
        [
            "☀️ হ্যাঁ আজকে গরম প্রচুর! তাই সবাই ঠাণ্ডা স্থানে থাকুন এবং লেবুর শরবত খান। 🍋🥤❤️",

            "🥵 গরম তো বেশিই! পানি বেশি পান করুন, রোদ এড়িয়ে চলুন। 💧☀️",

            "☀️🥵 আজকের গরমে বাইরে গেলে পানি সঙ্গে রাখবেন। লেবুর শরবত হলে আরও ভালো! 🍋🥤",

            "আহা কী গরম! 🥵❄️ একটু ঠাণ্ডা জায়গায় বসুন আর পানি পান করুন। 💧",
        ]
    ),

    # --------------------------------------------------------
    # Winter / cold
    # --------------------------------------------------------

    (
        [
            "অনেক শীত",
            "আজ অনেক শীত",
            "আজকে শীত",
            "শীত পড়ছে",
            "শীত লাগছে",
            "খুব ঠান্ডা",
            "ঠান্ডা লাগছে",
            "শীত",
            "winter",
        ],
        [
            "❄️🥶 কম্বল গায়ে দাও আর প্রিয় মানুষটাকে জড়িয়ে ধরে ঘুমাও। 😴❤️",

            "🥶❄️ শীত বেশি হলে গরম কাপড় পরুন আর কম্বলটা শক্ত করে ধরুন। 😂🧣",

            "❄️ আজ তো কম্বল ছাড়া চলবে না! 😴🛌 গরম থাকুন ভাই। ❤️",

            "🥶☕ শীতের দিনে গরম চা + কম্বল = শান্তি! ☕🧣❤️",
        ]
    ),

    # --------------------------------------------------------
    # Bathing
    # --------------------------------------------------------

    (
        [
            "গোসল করবো না",
            "গোসল করব না",
            "আজ গোসল করবো না",
            "আজ গোসল করব না",
            "গোসল করবো না আজ",
            "গোসল করব না আজ",
        ],
        [
            "😂 দোস্ত, কত দিন ধরে গোসল করছ না? 🛁🤣 আজকে কিন্তু গোসল করো!",

            "🤣 ভাই, পানি তোমার কী দোষ করেছে? 🛁😂 যাও, গোসল করে আসো!",

            "😳 গোসল বাদ দিলে কিন্তু মানুষ না, ইতিহাস হয়ে যাবে! 😂🛁",

            "🛁😂 আজ গোসল না করলে কালকে তোমার আশেপাশের মানুষই নোটিফিকেশন দেবে! 🤣",
        ]
    ),

    (
        [
            "গোসল",
            "গোসল করতে",
            "গোসল করার সময়",
            "bath",
            "bathing",
        ],
        [
            "🛁 গোসলের সময় হলে এখনই করে ফেলুন। পরে করলে আলসেমি এসে যাবে। 😄",
            "🚿🛁 ফ্রেশ হয়ে নিন ভাই, মনটাও ভালো হয়ে যাবে। 😊",
            "🧼🚿 একটু ফ্রেশ হয়ে আসুন—তারপর আবার কাজ/আড্ডা। 😎",
        ]
    ),

    # --------------------------------------------------------
    # Sleep
    # --------------------------------------------------------

    (
        [
            "ঘুমাব",
            "ঘুমাবো",
            "ঘুমাতে যাব",
            "ঘুমাতে যাচ্ছি",
            "ঘুমানোর সময়",
            "ঘুমাব এখন",
            "ঘুমাবো এখন",
            "ঘুম",
            "sleep",
        ],
        [
            "😴🌙 ঘুমের সময় হলে ফোনটা পাশে রেখে আরামে ঘুমান। শুভ রাত্রি। ❤️",

            "🌙😴 ভালো করে ঘুমান। কালকে নতুন দিন, নতুন কাজ। 💪❤️",

            "😂 ফোনটা নামাও ভাই, TikTok/Telegram আর কত? এখন ঘুম! 😴📱",

            "🌙💤 চোখ বন্ধ করুন, চিন্তা কমান, ঘুমিয়ে পড়ুন। ❤️😴",
        ]
    ),

    # --------------------------------------------------------
    # Food
    # --------------------------------------------------------

    (
        [
            "খাব",
            "খাবো",
            "খেতে বসছি",
            "খেতে যাব",
            "খাবার সময়",
            "খাওয়ার সময়",
            "খিদা লাগছে",
            "ক্ষুধা লাগছে",
            "খাবার",
            "খাওয়া",
        ],
        [
            "🍚😋 সময়মতো খাবার খেয়ে নিন। খালি পেটে বেশি সময় থাকবেন না। ❤️",

            "🍛 ক্ষুধা লাগলে আর দেরি কেন? খেয়ে নিন ভাই! 😄🍽️",

            "🍚❤️ খাবার আগে হাত ধুয়ে নিন, তারপর শান্তিতে খাবার খান। 😊",

            "😋🍽️ খাওয়ার সময় ফোনটা একটু পাশে রাখলে খাবারটাও ভালোভাবে উপভোগ করতে পারবেন।",
        ]
    ),

    # --------------------------------------------------------
    # Cooking
    # --------------------------------------------------------

    (
        [
            "রান্না করবো",
            "রান্না করব",
            "রান্না করছি",
            "রান্না করার সময়",
            "রান্না",
            "cooking",
            "cook কর",
        ],
        [
            "👨‍🍳🔥 রান্নার সময় সাবধানে কাজ করুন। আজ কী রান্না হচ্ছে? 😋",

            "🍳😋 রান্নার গন্ধ কিন্তু এখান পর্যন্ত আসছে মনে হচ্ছে! 😂❤️",

            "👨‍🍳🍲 রান্না সুন্দর হোক! লবণ যেন বেশি না হয় কিন্তু। 😂",

            "🔥🍳 Chef mode ON! 😎👨‍🍳",
        ]
    ),

    # --------------------------------------------------------
    # Study
    # --------------------------------------------------------

    (
        [
            "পড়তে বসছি",
            "পড়াশোনা করব",
            "পড়াশোনা করছি",
            "পড়ার সময়",
            "পড়তে হবে",
            "স্টাডি",
            "study",
            "exam",
            "পরীক্ষা",
        ],
        [
            "📚🔥 মন দিয়ে পড়ুন ভাই। আজকের পড়া আজই শেষ করুন। 💪",

            "📖🎯 ফোনটা একটু দূরে রাখুন, ৩০ মিনিট মন দিয়ে পড়ুন। তারপর বিরতি। 😊",

            "🎓📚 অল্প অল্প করে নিয়মিত পড়লেই বড় ফল আসে। Keep going! 💪",

            "📝🔥 পরীক্ষার ভয় না পেয়ে আজকের কাজটা আজই শেষ করুন। ❤️",
        ]
    ),

    # --------------------------------------------------------
    # Work
    # --------------------------------------------------------

    (
        [
            "কাজ করতে বসছি",
            "কাজ করছি",
            "কাজের সময়",
            "অফিসে যাচ্ছি",
            "অফিস",
            "কাজ করতে হবে",
            "work",
        ],
        [
            "💼🔥 কাজটা একবারে এক ধাপ করে করুন। আপনি পারবেন! 💪",

            "💻🎯 আগে সবচেয়ে জরুরি কাজটা শেষ করুন। তারপর বাকিগুলো।",

            "💼😊 কাজের মাঝে ছোট বিরতি নিতে ভুলবেন না।",

            "🔥💪 কাজ শুরু হয়ে গেলে ফোনের distraction একটু কমিয়ে দিন।",
        ]
    ),

    # --------------------------------------------------------
    # Sports
    # --------------------------------------------------------

    (
        [
            "খেলতে যাব",
            "খেলতে যাচ্ছি",
            "খেলা",
            "ক্রিকেট খেলব",
            "ফুটবল খেলব",
            "sports",
        ],
        [
            "🏏🔥 খেলতে যান, শরীরটাও ফিট থাকবে! 💪😊",

            "⚽😎 খেলা হোক জমজমাট! তবে পানি সঙ্গে রাখবেন। 💧",

            "🏆🔥 আজকে জয় আপনারই হোক! 💪😄",
        ]
    ),

    # --------------------------------------------------------
    # Fighting
    # --------------------------------------------------------

    (
        [
            "ঝগড়া করব",
            "ঝগড়া করছি",
            "মারামারি",
            "মারামারি করব",
            "লড়াই করব",
            "ফাইট করব",
            "fight",
            "ঝামেলা করব",
        ],
        [
            "🕊️❤️ ঝগড়া না করে শান্তভাবে কথা বলুন। রাগের সময় নেওয়া সিদ্ধান্ত পরে আফসোস হতে পারে।",

            "🤝 শান্ত হন ভাই। মারামারি করে কোনো লাভ নেই—কথা বলে সমাধান করুন। ❤️",

            "😌✋ আগে শান্ত হন, পানি খান, তারপর কথা বলুন। ঝগড়া বাদ! ❤️",

            "🕊️ মানুষের সাথে সম্পর্ক জেতা ভালো, ঝগড়া জেতা নয়। ❤️",
        ]
    ),

    # --------------------------------------------------------
    # Love
    # --------------------------------------------------------

    (
        [
            "ভালোবাসি",
            "আমি তোমাকে ভালোবাসি",
            "তোমাকে ভালোবাসি",
            "love you",
            "i love you",
        ],
        [
            "😂❤️ আমি তো AI ভাই, তবে আপনার ভালোবাসার সম্মান রাখলাম! 🤖❤️",

            "🥹❤️ এত ভালোবাসা কোথায় রাখি বলুন তো! 😄",

            "🤖❤️ আপনার ভালোবাসা গ্রহণ করলাম—Boss-এর অনুমতি লাগবে না তো? 😂👑",
        ]
    ),

    # --------------------------------------------------------
    # Sad
    # --------------------------------------------------------

    (
        [
            "মন খারাপ",
            "মনটা খারাপ",
            "খারাপ লাগছে",
            "দুঃখ লাগছে",
            "sad",
            "depressed",
        ],
        [
            "🥺❤️ মন খারাপ হলে একা থাকবেন না। কাছের কারও সাথে কথা বলুন।",

            "🫂❤️ সব দিন একরকম যায় না। খারাপ সময়ও একসময় চলে যায়।",

            "🌿❤️ একটু বাইরে হাঁটুন, পানি পান করুন, আর নিজের যত্ন নিন।",
        ]
    ),

    # --------------------------------------------------------
    # Happy
    # --------------------------------------------------------

    (
        [
            "অনেক খুশি",
            "খুশি লাগছে",
            "আজ ভালো লাগছে",
            "happy",
            "ভালো লাগছে",
        ],
        [
            "🥳❤️ এই তো চাই! আপনার খুশিটা এমনই থাকুক।",

            "😄🔥 আজকে তাহলে আনন্দের দিন! উপভোগ করুন ভাই।",

            "🎉😊 ভালো লাগলে কারণটা মনে রাখবেন—খারাপ দিনে কাজে লাগবে। ❤️",
        ]
    ),

    # --------------------------------------------------------
    # Bored
    # --------------------------------------------------------

    (
        [
            "বোর লাগছে",
            "boring",
            "bored",
            "বোর হচ্ছি",
            "কিছু ভালো লাগছে না",
        ],
        [
            "😂🎬 একটা নাটক দেখবেন? Category থেকে পছন্দ করে নিন।",

            "😎🔥 বোরিং বাদ! গান, নাটক, মুভি—কী চাই বলুন।",

            "🎵😄 একটা গান শুনুন, তারপর একটু হাঁটাহাঁটি করুন।",
        ]
    ),

    # --------------------------------------------------------
    # Thank / compliment
    # --------------------------------------------------------

    (
        [
            "তুমি ভালো",
            "তুমি অনেক ভালো",
            "বটটা ভালো",
            "nice bot",
            "good bot",
        ],
        [
            "🥹❤️ ধন্যবাদ ভাই! Boss শুনলে খুশি হবে। 👑",

            "😎🔥 ধন্যবাদ! আমি তো Boss-এর শেখানো কথা শুনি। 👑",
            "🤖❤️ আপনার ভালো লাগলেই আমার কাজ সফল।",
        ]
    ),
]


def smart_everyday_reply(
    text
):

    norm = normalize_text(
        text
    )

    if not norm:
        return None

    # Rules are ordered intentionally.
    for patterns, replies in SMART_REPLY_RULES:

        for pattern in patterns:

            p = normalize_text(
                pattern
            )

            if not p:
                continue

            if p in norm:

                return random.choice(
                    replies
                )

    return None

# ============================================================================
# ADMIN HELP
# ============================================================================


def is_admin(user_id):

    return user_id in ADMIN_IDS


async def handle_admin_help(
    message,
    context,
    user,
    text
):

    norm = normalize_text(
        text
    )

    help_words = [
        "এডমিন চাই",
        "অ্যাডমিন চাই",
        "admin help",
        "এডমিনের সাথে",
        "সমস্যা হয়েছে",
        "অভিযোগ",
        "admin contact",
        "contact admin",
    ]

    if any(
        w in norm
        for w in help_words
    ):

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 এডমিন @"
                    + ADMIN_USERNAME
                    + "-কে মেসেজ দিন",
                    url=(
                        f"https://t.me/"
                        f"{ADMIN_USERNAME}"
                    )
                )
            ]
        ])

        await message.reply_text(
            f"👑 এডমিনের সাথে যোগাযোগ: "
            f"@{ADMIN_USERNAME}",
            reply_markup=keyboard
        )

        await notify_admin_user_help(
            context.bot,
            user,
            text
        )

        return True

    return False

# ============================================================================
# COMMANDS
# ============================================================================


async def start_command(
    update,
    context
):

    user = update.effective_user

    save_user(user)
    save_chat(
        update.effective_chat
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎬 নাটক চাই",
                callback_data="show_dramas"
            ),
            InlineKeyboardButton(
                "🎵 গান চাই",
                callback_data="show_songs"
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 ট্রেন্ডিং",
                callback_data="show_trending"
            ),
            InlineKeyboardButton(
                "📂 সব Category",
                callback_data="usercat_page:0"
            )
        ],
        [
            InlineKeyboardButton(
                "🌤️ আবহাওয়া",
                callback_data="show_weather"
            ),
            InlineKeyboardButton(
                "🕌 নামাজ",
                callback_data="show_prayer"
            )
        ],
        [
            InlineKeyboardButton(
                "👑 এডমিন: @"
                + ADMIN_USERNAME,
                url=(
                    f"https://t.me/"
                    f"{ADMIN_USERNAME}"
                )
            )
        ]
    ])

    await update.effective_message.reply_text(
        f"👋 আসসালামু আলাইকুম "
        f"{user.first_name}!\n\n"
        "আমি আপনার AI Telegram Bot। 🤖\n\n"
        "✨ যেকোনো প্রশ্ন করতে পারেন।\n"
        "🎬 নাটক/গান/ভিডিওর নাম লিখে খুঁজতে পারেন।\n"
        "📂 Category-এর নাম লিখুন।\n"
        "💬 সাধারণ কথাও বলতে পারেন।\n\n"
        "উদাহরণ:\n"
        "• নাটক\n"
        "• নাটক দেন\n"
        "• গান দেও\n"
        "• শীত\n"
        "• শীতের ভিডিও দেখাও\n"
        "• ক্রিকেট আছে?\n"
        "• আজ অনেক গরম\n"
        "• আজ বৃষ্টি হচ্ছে\n\n"
        f"👑 Boss: {BOSS_NAME}\n"
        f"📱 {BOSS_USERNAME}",
        reply_markup=keyboard
    )


async def help_command(
    update,
    context
):

    await update.effective_message.reply_text(
        "📖 বটের ব্যবহারবিধি:\n\n"
        "1️⃣ যেকোনো প্রশ্ন লিখুন → AI উত্তর দেবে।\n"
        "2️⃣ Category-এর নাম লিখুন → সেই Category দেখাবে।\n"
        "3️⃣ নাটক/গান/ভিডিওর নাম লিখুন → DB-তে থাকলে পাঠাবে।\n"
        "4️⃣ /trending → ট্রেন্ডিং কন্টেন্ট\n"
        "5️⃣ /weather → আবহাওয়া\n"
        "6️⃣ /prayer → নামাজের সময়\n"
        "7️⃣ /categories → সব Category\n"
        "8️⃣ /auto_on → অটো নোটিফিকেশন চালু\n"
        "9️⃣ /auto_off → অটো নোটিফিকেশন বন্ধ\n\n"
        f"👑 Boss: {BOSS_NAME}\n"
        f"📱 {BOSS_USERNAME}"
    )


async def contact_command(
    update,
    context
):

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 এডমিনকে মেসেজ দিন",
                url=(
                    f"https://t.me/"
                    f"{ADMIN_USERNAME}"
                )
            )
        ]
    ])

    await update.effective_message.reply_text(
        f"👑 এডমিন যোগাযোগ\n\n"
        f"@{ADMIN_USERNAME}\n"
        f"ID: {ADMIN_IDS[0]}",
        reply_markup=keyboard
    )


async def admin_panel_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.effective_message.reply_text(
            "⛔ এই কমান্ডটি শুধুমাত্র এডমিনের জন্য।"
        )

        return

    await update.effective_message.reply_text(
        f"👑 এডমিন প্যানেল (@{ADMIN_USERNAME})\n\n"
        "📥 ভিডিও/অডিও/ছবি পাঠান → Title → Category → DB Save হবে।\n\n"
        "📂 Category Management:\n"
        "/categories - Category list\n"
        "/addcategory - নতুন Category\n"
        "/editcategory - Category edit\n"
        "/delcategory - Category বন্ধ\n\n"
        "📚 Content:\n"
        "/list - কন্টেন্ট তালিকা\n"
        "/stats - পরিসংখ্যান\n"
        "/delete <ID> - কন্টেন্ট Delete\n\n"
        "🔔 Notification:\n"
        "/auto_on\n"
        "/auto_off\n"
        "/notify_test"
    )


async def categories_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):

        text, markup = category_prompt(
            prefix="usercat",
            page=0,
            heading="📂 সব Category"
        )

        await update.effective_message.reply_text(
            text,
            reply_markup=markup
        )

        return

    rows = get_categories(
        active_only=False
    )

    if not rows:

        await update.effective_message.reply_text(
            "📭 কোনো Category নেই।"
        )

        return

    lines = [
        "📂 Category List\n"
    ]

    for index, row in enumerate(
        rows,
        1
    ):

        status = (
            "✅"
            if row["active"]
            else "❌"
        )

        lines.append(
            f"{index}. {status} "
            f"{row['key']} → "
            f"{row['label']}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000]
    )


async def addcategory_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if len(context.args) < 2:

        await update.effective_message.reply_text(
            "ব্যবহার:\n"
            "/addcategory key | label | aliases\n\n"
            "উদাহরণ:\n"
            "/addcategory winter2 | ❄️ শীতের ভিডিও 2 | "
            "শীতের ভিডিও,শীত ২,winter 2"
        )

        return

    raw = " ".join(
        context.args
    )

    parts = [
        p.strip()
        for p in raw.split("|")
    ]

    key = clean_category_key(
        parts[0]
    )

    label = (
        parts[1]
        if len(parts) > 1
        else key
    )

    aliases = (
        parts[2]
        if len(parts) > 2
        else label
    )

    if not key:

        await update.effective_message.reply_text(
            "❌ Category key সঠিক নয়।"
        )

        return

    if category_exists(key):

        await update.effective_message.reply_text(
            "❌ এই Category আগে থেকেই আছে।"
        )

        return

    max_row = db_execute(
        """
        SELECT MAX(sort_order) AS m
        FROM categories
        """,
        fetchone=True
    )

    next_order = (
        (
            max_row["m"] or 0
        ) + 1
        if max_row
        else 1
    )

    db_execute(
        """
        INSERT INTO categories(
            key,
            label,
            aliases,
            sort_order,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            key,
            label,
            aliases,
            next_order,
            now_str(),
        )
    )

    await update.effective_message.reply_text(
        "✅ নতুন Category যোগ হয়েছে।\n\n"
        f"🔑 Key: {key}\n"
        f"🏷️ Label: {label}\n"
        f"🔎 Alias: {aliases}"
    )


async def editcategory_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if len(context.args) < 3:

        await update.effective_message.reply_text(
            "ব্যবহার:\n"
            "/editcategory key | নতুন label | নতুন aliases"
        )

        return

    raw = " ".join(
        context.args
    )

    parts = [
        p.strip()
        for p in raw.split("|")
    ]

    key = clean_category_key(
        parts[0]
    )

    label = parts[1]
    aliases = parts[2]

    row = get_category(
        key
    )

    if not row:

        await update.effective_message.reply_text(
            "❌ এই Category পাওয়া যায়নি।"
        )

        return

    db_execute(
        """
        UPDATE categories
        SET label=?,
            aliases=?,
            active=1
        WHERE key=?
        """,
        (
            label,
            aliases,
            key
        )
    )

    await update.effective_message.reply_text(
        "✅ Category Edit হয়েছে।\n\n"
        f"🔑 Key: {key}\n"
        f"🏷️ Label: {label}\n"
        f"🔎 Alias: {aliases}"
    )


async def delcategory_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "ব্যবহার:\n"
            "/delcategory <key>"
        )

        return

    key = clean_category_key(
        context.args[0]
    )

    row = get_category(
        key
    )

    if not row:

        await update.effective_message.reply_text(
            "❌ Category পাওয়া যায়নি।"
        )

        return

    db_execute(
        """
        UPDATE categories
        SET active=0
        WHERE key=?
        """,
        (key,)
    )

    await update.effective_message.reply_text(
        "✅ Category বন্ধ করা হয়েছে।\n\n"
        f"📂 {key}\n\n"
        "এই Category-এর পুরোনো content "
        "ডিলিট করা হয়নি।"
    )


async def list_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    rows = db_execute(
        """
        SELECT
            id,
            title,
            media_type,
            category,
            views
        FROM contents
        ORDER BY id DESC
        LIMIT 30
        """,
        fetch=True
    )

    if not rows:

        await update.effective_message.reply_text(
            "📭 এখনো কোনো কন্টেন্ট নেই।"
        )

        return

    lines = [
        "📚 সংরক্ষিত কন্টেন্ট:\n"
    ]

    labels = get_category_labels()

    for r in rows:

        label = labels.get(
            r["category"],
            r["category"]
        )

        lines.append(
            f"🆔 {r['id']} | "
            f"🎬 {r['title']} | "
            f"📁 {label} | "
            f"👁️ {r['views']}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000]
    )


async def delete_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "ব্যবহার: /delete <ID>"
        )

        return

    try:

        cid = int(
            context.args[0]
        )

        db_execute(
            "DELETE FROM contents WHERE id=?",
            (cid,)
        )

        await update.effective_message.reply_text(
            f"✅ ID {cid} ডিলিট হয়েছে।"
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ ডিলিট করতে সমস্যা: {e}"
        )


async def stats_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    u = db_execute(
        "SELECT COUNT(*) c FROM users",
        fetchone=True
    )["c"]

    c = db_execute(
        "SELECT COUNT(*) c FROM contents",
        fetchone=True
    )["c"]

    v = db_execute(
        "SELECT SUM(views) s FROM contents",
        fetchone=True
    )["s"] or 0

    chats = db_execute(
        "SELECT COUNT(*) c FROM chats",
        fetchone=True
    )["c"]

    cats = db_execute(
        "SELECT COUNT(*) c FROM categories "
        "WHERE active=1",
        fetchone=True
    )["c"]

    await update.effective_message.reply_text(
        f"📊 বট স্ট্যাটিস্টিক্স\n\n"
        f"👤 ইউজার: {u}\n"
        f"💬 চ্যাট: {chats}\n"
        f"🎬 কন্টেন্ট: {c}\n"
        f"📂 Active Category: {cats}\n"
        f"👁️ ভিউ: {v}"
    )


async def auto_on_command(
    update,
    context
):

    save_chat(
        update.effective_chat
    )

    set_chat_notifications(
        update.effective_chat.id,
        True
    )

    await update.effective_message.reply_text(
        "🔔 এই চ্যাটে অটো নোটিফিকেশন চালু হয়েছে।"
    )


async def auto_off_command(
    update,
    context
):

    save_chat(
        update.effective_chat
    )

    set_chat_notifications(
        update.effective_chat.id,
        False
    )

    await update.effective_message.reply_text(
        "🔕 এই চ্যাটে অটো নোটিফিকেশন বন্ধ হয়েছে।"
    )


async def notify_test_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    await update.effective_message.reply_text(
        hourly_message(
            datetime.now(TZ).hour
        )
    )


async def trending_command(
    update,
    context
):

    items = get_top_trending(
        10
    )

    if not items:

        await update.effective_message.reply_text(
            "📭 কোনো কন্টেন্ট নেই।"
        )

        return

    buttons = []

    for index, item in enumerate(
        items,
        1
    ):

        buttons.append([
            InlineKeyboardButton(
                f"{index}. 🎬 "
                f"{item['title'][:55]}",
                callback_data=(
                    f"send_media_{item['id']}"
                )
            )
        ])

    await update.effective_message.reply_text(
        "🔥 ট্রেন্ডিং কন্টেন্ট:\n\n"
        "যেটি চান সেটি নির্বাচন করুন।",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


async def weather_command(
    update,
    context
):

    await update.effective_message.reply_text(
        (
            await get_weather()
        )
        or
        "❌ আবহাওয়া তথ্য পাওয়া যায়নি।"
    )


async def prayer_command(
    update,
    context
):

    await update.effective_message.reply_text(
        (
            await get_prayer_times()
        )
        or
        "❌ নামাজের সময় পাওয়া যায়নি।"
    )

# ============================================================================
# CALLBACK QUERIES
# ============================================================================


async def handle_callback_query(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # ------------------------------------------------------------
    # Admin category pagination
    # ------------------------------------------------------------

    if data.startswith(
        "admincat_page:"
    ):

        try:

            page = int(
                data.split(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            page = 0

        text, markup = category_prompt(
            prefix="admincat",
            page=page
        )

        await query.message.reply_text(
            text,
            reply_markup=markup
        )

        return

    # ------------------------------------------------------------
    # Admin category
    # ------------------------------------------------------------

    if data.startswith(
        "admincat:"
    ):

        key = data.split(
            ":",
            1
        )[1]

        if not is_admin(
            query.from_user.id
        ):

            await query.message.reply_text(
                "❌ শুধু Admin Category নির্বাচন করতে পারবেন।"
            )

            return

        if not context.user_data.get(
            "waiting_category"
        ):

            await query.message.reply_text(
                "ℹ️ বর্তমানে কোনো মিডিয়া "
                "Category নির্বাচন করার অপেক্ষায় নেই।"
            )

            return

        pending = context.user_data.get(
            "pending_media"
        )

        title = context.user_data.get(
            "pending_title"
        )

        if not pending or not title:

            await query.message.reply_text(
                "❌ Pending upload পাওয়া যায়নি। "
                "ভিডিওটি আবার পাঠান।"
            )

            return

        category = get_category(
            key
        )

        if not category:

            await query.message.reply_text(
                "❌ Category পাওয়া যায়নি।"
            )

            return

        new_id = db_execute(
            """
            INSERT INTO contents(
                title,
                media_type,
                file_id,
                category,
                views,
                added_by,
                created_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                title,
                pending["media_type"],
                pending["file_id"],
                key,
                query.from_user.id,
                now_str(),
            )
        )

        context.user_data.pop(
            "pending_media",
            None
        )

        context.user_data.pop(
            "pending_title",
            None
        )

        context.user_data[
            "waiting_category"
        ] = False

        await query.message.reply_text(
            "🎉 SUCCESSFUL! কন্টেন্ট সংরক্ষণ হয়েছে।\n\n"
            f"🆔 ID: {new_id}\n"
            f"🎬 Title: {title}\n"
            f"📁 Media: {pending['media_type']}\n"
            f"🏷️ Category: {category['label']}\n\n"
            "👤 User এখন এই Category সিলেক্ট করলে "
            "কন্টেন্টটি পাবে।"
        )

        return

    # ------------------------------------------------------------
    # User category pagination
    # ------------------------------------------------------------

    if data.startswith(
        "usercat_page:"
    ):

        try:

            page = int(
                data.split(
                    ":",
                    1
                )[1]
            )

        except ValueError:

            page = 0

        text, markup = category_prompt(
            prefix="usercat",
            page=page
        )

        await query.message.reply_text(
            text,
            reply_markup=markup
        )

        return

    # ------------------------------------------------------------
    # User category
    # ------------------------------------------------------------

    if data.startswith(
        "usercat:"
    ):

        key = data.split(
            ":",
            1
        )[1]

        await show_category_content(
            query.message,
            key,
            send_waiting=True
        )

        return

    # ------------------------------------------------------------
    # Drama
    # ------------------------------------------------------------

    if data == "show_dramas":

        await show_category_content(
            query.message,
            "natok",
            send_waiting=True
        )

        return

    # ------------------------------------------------------------
    # Songs
    # ------------------------------------------------------------

    if data == "show_songs":

        await show_category_content(
            query.message,
            "music",
            send_waiting=True
        )

        return

    # ------------------------------------------------------------
    # Trending
    # ------------------------------------------------------------

    if data == "show_trending":

        items = get_top_trending(
            5
        )

        if not items:

            await query.message.reply_text(
                "📭 কোনো কন্টেন্ট নেই।"
            )

            return

        buttons = []

        for i, item in enumerate(
            items,
            1
        ):

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. 🎬 "
                    f"{item['title'][:55]}",
                    callback_data=(
                        f"send_media_{item['id']}"
                    )
                )
            ])

        await query.message.reply_text(
            "🔥 ট্রেন্ডিং কন্টেন্ট:\n\n"
            "যেটি চান সেটি নির্বাচন করুন।",
            reply_markup=InlineKeyboardMarkup(
                buttons
            )
        )

        return

    # ------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------

    if data == "show_weather":

        await query.message.reply_text(
            (
                await get_weather()
            )
            or
            "❌ আবহাওয়া তথ্য পাওয়া যায়নি।"
        )

        return

    # ------------------------------------------------------------
    # Prayer
    # ------------------------------------------------------------

    if data == "show_prayer":

        await query.message.reply_text(
            (
                await get_prayer_times()
            )
            or
            "❌ নামাজের সময় পাওয়া যায়নি।"
        )

        return

    # ------------------------------------------------------------
    # Media
    # ------------------------------------------------------------

    if data.startswith(
        "send_media_"
    ):

        try:

            cid = int(
                data.split("_")[-1]
            )

        except ValueError:

            await query.message.reply_text(
                "❌ ID সঠিক নয়।"
            )

            return

        row = db_execute(
            """
            SELECT *
            FROM contents
            WHERE id=?
            """,
            (cid,),
            fetchone=True
        )

        if row:

            await deliver_media(
                update,
                row
            )

        else:

            await query.message.reply_text(
                "❌ কন্টেন্ট পাওয়া যায়নি।"
            )

        return

# ============================================================================
# GROUP / MEMBER UPDATE
# ============================================================================


async def my_chat_member_handler(
    update,
    context
):

    cm = update.my_chat_member

    if not cm or not cm.chat:
        return

    save_chat(
        cm.chat
    )

    logger.info(
        "MY_CHAT_MEMBER | chat_id=%s | type=%s | old=%s | new=%s",
        cm.chat.id,
        cm.chat.type,
        cm.old_chat_member.status,
        cm.new_chat_member.status,
    )

# ============================================================================
# MAIN MESSAGE PROCESSOR
# ============================================================================


async def handle_all_messages(
    update,
    context
):

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if (
        not message
        or not user
        or not chat
    ):
        return

    logger.info(
        "MESSAGE RECEIVED | chat_id=%s | "
        "chat_type=%s | user=%s | text=%r",
        chat.id,
        chat.type,
        user.username or user.id,
        message.text,
    )

    save_user(user)
    save_chat(chat)

    # ------------------------------------------------------------
    # Admin media upload
    # ------------------------------------------------------------

    if await handle_admin_media_upload(
        update,
        context
    ):
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # ------------------------------------------------------------
    # Admin title
    # ------------------------------------------------------------

    if await handle_admin_title_save(
        update,
        context
    ):
        return

    # ------------------------------------------------------------
    # Rate limit
    # ------------------------------------------------------------

    if not check_rate_limit(
        user.id
    ):

        await message.reply_text(
            "⏳ একটু ধীরে মেসেজ করুন, "
            "আমি শুনছি। 🙂"
        )

        return

    norm = normalize_text(
        text
    )

    # ------------------------------------------------------------
    # ADMIN HELP
    # ------------------------------------------------------------

    if await handle_admin_help(
        message,
        context,
        user,
        text
    ):
        return

    # ------------------------------------------------------------
    # CREATOR / BOSS - VERY FAST
    # ------------------------------------------------------------

    creator_keywords = [
        "তোমাকে কে তৈরি",
        "তোমাকে কে বানাইছে",
        "তোমাকে কে বানিয়েছে",
        "কে তোমাকে বানিয়েছে",
        "তোমার creator কে",
        "creator কে",
        "who created you",
        "who made you",
        "তোমার boss কে",
        "তোমার বস কে",
    ]

    if any(
        x in norm
        for x in creator_keywords
    ):

        await message.reply_text(
            random.choice([
                "🤖 আমার Boss, TOMAL CHOWDHURY আমাকে তৈরি করছে। 👑\n"
                "Boss: @tomalchowdhury2 ❤️",

                "😎 আমাকে তৈরি করছে আমার Boss TOMAL CHOWDHURY। 👑\n"
                "Username: @tomalchowdhury2",

                "🤖 আমার Boss হলেন TOMAL CHOWDHURY। 👑🔥\n"
                "আমি Boss-এর কথা শুনি।\n"
                "@tomalchowdhury2",
            ])
        )

        return

    # ------------------------------------------------------------
    # HOME / LOCATION - VERY FAST
    # ------------------------------------------------------------

    home_keywords = [
        "তুমি কোথায় থাকো",
        "তুমি কই থাকো",
        "তোমার বাসা কোথায়",
        "তোমার বাড়ি কোথায়",
        "where do you live",
        "where is your home",
    ]

    if any(
        x in norm
        for x in home_keywords
    ):

        await message.reply_text(
            "🏠 আমার কোনো বাসা নেই, "
            "আমি আমার user name, TOMAL CHOWDHURY বসের সাথে "
            "থাকি এবং বসের কথা শুনি। 😎\n\n"
            "👑 Boss: @tomalchowdhury2"
        )

        return

    # ------------------------------------------------------------
    # WEATHER / PRAYER FIRST
    # ------------------------------------------------------------

    if any(
        w in norm
        for w in [
            "আবহাওয়া",
            "weather",
            "তাপমাত্রা",
        ]
    ):

        await message.reply_text(
            (
                await get_weather()
            )
            or
            "❌ আবহাওয়া তথ্য পাওয়া যায়নি।"
        )

        return

    if any(
        w in norm
        for w in [
            "নামাজের সময়",
            "নামাজ কখন",
            "আজকের নামাজ",
            "prayer time",
        ]
    ):

        await message.reply_text(
            (
                await get_prayer_times()
            )
            or
            "❌ নামাজের সময় পাওয়া যায়নি।"
        )

        return

    # ------------------------------------------------------------
    # FAST EVERYDAY SMART REPLY
    #
    # This happens BEFORE OpenAI.
    # ------------------------------------------------------------

    smart_reply = smart_everyday_reply(
        text
    )

    if smart_reply:

        await message.reply_text(
            smart_reply
        )

        return

    # ------------------------------------------------------------
    # CATEGORY
    # ------------------------------------------------------------

    category_key = detect_category_intent(
        text
    )

    if (
        category_key
        and is_category_request(text)
    ):

        category = get_category(
            category_key
        )

        if category:

            # User requested waiting message first.
            await message.reply_text(
                "অবশ্যই একটু অপেক্ষা করুন দিচ্ছি.. ⏳😊"
            )

            await show_category_content(
                message,
                category_key,
                send_waiting=False
            )

            return

    # ------------------------------------------------------------
    # CONTENT SEARCH
    # ------------------------------------------------------------

    is_drama_query = any(
        k in norm
        for k in [
            "নাটক",
            "drama",
            "natok",
        ]
    )

    is_song_query = any(
        k in norm
        for k in [
            "গান",
            "song",
            "গজল",
            "audio",
            "music",
        ]
    )

    is_video_query = any(
        k in norm
        for k in [
            "ভিডিও",
            "video",
            "মুভি",
            "movie",
        ]
    )

    is_content_intent = (
        is_drama_query
        or is_song_query
        or is_video_query
        or any(
            r in norm
            for r in [
                "চাই",
                "দাও",
                "দেন",
                "পাঠাও",
                "পাঠান",
                "লাগবে",
                "দেও",
            ]
        )
    )

    if is_content_intent:

        target_category = None

        if is_drama_query:
            target_category = "natok"

        elif is_song_query:
            target_category = "music"

        clean_query = norm

        remove_words = [
            "আমাকে",
            "একটি",
            "একটা",
            "নাটক",
            "গান",
            "ভিডিও",
            "দাও",
            "দেন",
            "চাই",
            "লাগবে",
            "নতুন",
            "প্লিজ",
            "please",
            "দেও",
            "পাঠাও",
            "পাঠান",
            "আছে",
            "দেখাও",
            "দেখান",
            "দিবে",
            "দিবেন",
        ]

        for rm in remove_words:

            clean_query = re.sub(
                r"\b"
                + re.escape(rm)
                + r"\b",
                " ",
                clean_query
            )

        clean_query = re.sub(
            r"\s+",
            " ",
            clean_query
        ).strip()

        # --------------------------------------------------------
        # Specific content
        # --------------------------------------------------------

        if clean_query:

            found = search_content(
                clean_query,
                target_category
            )

            if found:

                await message.reply_text(
                    "অবশ্যই একটু অপেক্ষা করুন দিচ্ছি.. ⏳😊"
                )

                await deliver_media(
                    update,
                    found
                )

                return

        # --------------------------------------------------------
        # Generic নাটক
        # --------------------------------------------------------

        if (
            is_drama_query
            and not clean_query
        ):

            await message.reply_text(
                "অবশ্যই একটু অপেক্ষা করুন দিচ্ছি.. ⏳😊"
            )

            await show_category_content(
                message,
                "natok",
                send_waiting=False
            )

            return

        # --------------------------------------------------------
        # Generic গান
        # --------------------------------------------------------

        if (
            is_song_query
            and not clean_query
        ):

            await message.reply_text(
                "অবশ্যই একটু অপেক্ষা করুন দিচ্ছি.. ⏳😊"
            )

            await show_category_content(
                message,
                "music",
                send_waiting=False
            )

            return

        # --------------------------------------------------------
        # Generic video
        # --------------------------------------------------------

        if (
            is_drama_query
            or is_song_query
            or is_video_query
        ):

            category_to_show = (
                target_category
                or "other"
            )

            recs = get_contents_by_category(
                category_to_show,
                5
            )

            buttons = []

            for r in recs:

                buttons.append([
                    InlineKeyboardButton(
                        f"🎬 {r['title'][:55]}",
                        callback_data=(
                            f"send_media_{r['id']}"
                        )
                    )
                ])

            buttons.append([
                InlineKeyboardButton(
                    "📂 Category দেখুন",
                    callback_data="usercat_page:0"
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    "📩 এডমিনকে আপলোডের অনুরোধ",
                    url=(
                        f"https://t.me/"
                        f"{ADMIN_USERNAME}"
                    )
                )
            ])

            await message.reply_text(
                "অবশ্যই একটু অপেক্ষা করুন দিচ্ছি.. ⏳😊"
            )

            if recs:

                rec_text = (
                    "💡 জনপ্রিয় কন্টেন্ট:\n\n"
                    + "\n".join(
                        f"• {r['title']}"
                        for r in recs
                    )
                )

                await message.reply_text(
                    rec_text,
                    reply_markup=InlineKeyboardMarkup(
                        buttons
                    )
                )

            else:

                await message.reply_text(
                    "😔 এই Category-তে এখনো কন্টেন্ট নেই।\n\n"
                    "📩 নতুন কন্টেন্টের জন্য Admin-কে জানানো হয়েছে।",
                    reply_markup=InlineKeyboardMarkup(
                        buttons
                    )
                )

                await notify_admin_missing_content(
                    context.bot,
                    user,
                    category_to_show,
                    text
                )

            return

    # ------------------------------------------------------------
    # OPENAI FALLBACK
    # ------------------------------------------------------------

    save_message(
        chat.id,
        user.id,
        "user",
        text
    )

    try:

        await message.reply_chat_action(
            "typing"
        )

    except Exception:
        pass

    ai_reply = await generate_chatgpt_response(
        chat.id,
        text
    )

    save_message(
        chat.id,
        0,
        "assistant",
        ai_reply
    )

    await message.reply_text(
        ai_reply
    )

# ============================================================================
# RATE LIMIT
# ============================================================================


user_last_action = {}


def check_rate_limit(
    user_id,
    interval=0.7
):

    current = time.time()

    last = user_last_action.get(
        user_id,
        0
    )

    if (
        current - last
        < interval
    ):

        return False

    user_last_action[
        user_id
    ] = current

    return True

# ============================================================================
# GLOBAL ERROR
# ============================================================================


async def global_error_handler(
    update,
    context
):

    logger.error(
        "Exception while handling update: %s",
        context.error
    )

    try:

        tb = "".join(
            traceback.format_exception(
                type(context.error),
                context.error,
                context.error.__traceback__
            )
        )

    except Exception:

        tb = str(
            context.error
        )

    user = (
        update.effective_user
        if isinstance(
            update,
            Update
        )
        else None
    )

    try:

        await send_admin_alert(
            context.bot,
            "⚠️ **[ERROR ALERT]**\n"
            f"User: "
            f"{user.first_name if user else 'Unknown'}\n\n"
            f"`{str(context.error)}`\n\n"
            f"Traceback:\n"
            f"`{tb[-1200:]}`"
        )

    except Exception:
        pass

# ============================================================================
# STARTUP
# ============================================================================


async def post_init(
    application
):

    # Remove old webhook
    try:

        await application.bot.delete_webhook(
            drop_pending_updates=False
        )

        me = await application.bot.get_me()

        logger.info(
            "BOT CONNECTED | username=@%s | id=%s",
            me.username,
            me.id
        )

    except Exception as e:

        logger.error(
            "Bot startup check failed: %r",
            e
        )

    # AdsGram
    if ADSGRAM_ENABLED:

        logger.info(
            "AdsGram ENABLED | block=%s",
            ADSGRAM_NUMERIC_BLOCK_ID
        )

    else:

        logger.warning(
            "AdsGram DISABLED. "
            "Set ADSGRAM_BLOCK_ID and ADSGRAM_TOKEN."
        )

    # Automatic notifications
    if AUTO_MESSAGES_ENABLED:

        application.create_task(
            automatic_notification_loop(
                application
            ),
            name="automatic_notification_loop"
        )

# ============================================================================
# RUN BOT
# ============================================================================


def run_bot_once():

    if not BOT_TOKEN:

        print(
            "❌ Error: BOT_TOKEN is missing!"
        )

        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ------------------------------------------------------------
    # COMMANDS
    # ------------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "contact",
            contact_command
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_panel_command
        )
    )

    app.add_handler(
        CommandHandler(
            "categories",
            categories_command
        )
    )

    app.add_handler(
        CommandHandler(
            "addcategory",
            addcategory_command
        )
    )

    app.add_handler(
        CommandHandler(
            "editcategory",
            editcategory_command
        )
    )

    app.add_handler(
        CommandHandler(
            "delcategory",
            delcategory_command
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
            "delete",
            delete_command
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
            "auto_on",
            auto_on_command
        )
    )

    app.add_handler(
        CommandHandler(
            "auto_off",
            auto_off_command
        )
    )

    app.add_handler(
        CommandHandler(
            "notify_test",
            notify_test_command
        )
    )

    app.add_handler(
        CommandHandler(
            "trending",
            trending_command
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

    # ------------------------------------------------------------
    # CALLBACK
    # ------------------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            handle_callback_query
        )
    )

    # ------------------------------------------------------------
    # GROUP / MEMBER
    # ------------------------------------------------------------

    app.add_handler(
        ChatMemberHandler(
            my_chat_member_handler,
            ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    # ------------------------------------------------------------
    # MEDIA
    # ------------------------------------------------------------

    app.add_handler(
        MessageHandler(
            (
                filters.VIDEO
                | filters.AUDIO
                | filters.PHOTO
                | filters.Document.ALL
                | filters.ANIMATION
            ),
            handle_all_messages
        )
    )

    # ------------------------------------------------------------
    # TEXT
    # ------------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_all_messages
        )
    )

    app.add_error_handler(
        global_error_handler
    )

    # ------------------------------------------------------------
    # STARTUP INFORMATION
    # ------------------------------------------------------------

    print(
        "=================================================="
    )

    print(
        "🤖 Telegram Bot Running"
    )

    print(
        f"👑 Admin: @{ADMIN_USERNAME} "
        f"(ID: {ADMIN_IDS[0]})"
    )

    print(
        f"👑 Boss: {BOSS_NAME}"
    )

    print(
        f"📱 Boss Username: {BOSS_USERNAME}"
    )

    print(
        f"🧠 AI Model: {OPENAI_MODEL}"
    )

    print(
        "⚡ Fast Smart Reply Engine: ON"
    )

    print(
        "📂 Dynamic Category System: ON"
    )

    print(
        f"📂 Default Categories: "
        f"{len(DEFAULT_CATEGORIES)}+"
    )

    print(
        "📢 AdsGram: "
        + (
            "ON"
            if ADSGRAM_ENABLED
            else "OFF"
        )
    )

    if ADSGRAM_ENABLED:

        print(
            f"📢 AdsGram Block: "
            f"{ADSGRAM_NUMERIC_BLOCK_ID}"
        )

    print(
        "🔔 Auto notifications: "
        + (
            "ON"
            if AUTO_MESSAGES_ENABLED
            else "OFF"
        )
    )

    print(
        f"📚 Study hours: {STUDY_HOURS}"
    )

    print(
        f"⚽ Sports hours: {SPORTS_HOURS}"
    )

    print(
        f"🌅 Wake hour: {WAKE_HOUR}:00"
    )

    print(
        f"💼 Work hours: {WORK_HOURS}"
    )

    print(
        f"😴 Sleep hour: {SLEEP_HOUR}:00"
    )

    print(
        "🕌 Prayer notifications: ON"
    )

    print(
        "=================================================="
    )

    # ------------------------------------------------------------
    # LONG POLLING
    # ------------------------------------------------------------

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )

# ============================================================================
# MAIN
# ============================================================================


def main():

    init_db()

    retry_delay = 10

    while True:

        try:

            run_bot_once()

            logger.warning(
                "Bot polling stopped. "
                "Restarting in %s seconds...",
                retry_delay
            )

            time.sleep(
                retry_delay
            )

        except KeyboardInterrupt:

            logger.info(
                "Bot stopped by user."
            )

            break

        except Exception as e:

            logger.error(
                "Bot crashed / network connection failed: %r",
                e
            )

            logger.error(
                "Restarting automatically in %s seconds...",
                retry_delay
            )

            time.sleep(
                retry_delay
            )


if __name__ == "__main__":
    main()
