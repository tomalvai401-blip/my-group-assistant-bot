‎#!/usr/bin/env python3
‎-- coding: utf-8 --
‎
‎"""
‎Telegram AI Assistant & Media Bot - OpenAI + AdsGram
‎Admin: @tomalchowdhury2 (ID: 8721334265)
‎
‎FULL VERSION
‎
‎Kept features:
· ‎OpenAI AI replies
· ‎Admin media upload -> title -> category -> SQLite save
· ‎Drama/song/video/category search and delivery
· ‎Admin alerts
· ‎Weather and prayer times
· ‎Admin commands
· ‎Group-message handling/logging
· ‎Removes old Telegram webhook before polling
· ‎Saves groups when bot is added
· ‎Hourly automatic reminders
· ‎Exact prayer-time automatic reminders
· ‎Study, sports, work and sleep reminders
· ‎/auto_on and /auto_off per chat
‎
‎Added:
· ‎AdsGram Bot API ad before media delivery
· ‎Dynamic category system
· ‎Large category system
· ‎Admin add/edit/delete category
· ‎Natural category intent detection
· ‎Fast local replies before OpenAI
· ‎Bengali/Banglish understanding
· ‎Creator/Boss identity replies
· ‎Bot home/location reply
· ‎Rain / heat / winter smart replies
· ‎Food / cooking / bathing / sleeping replies
· ‎Funny replies
· ‎Apology replies
· ‎Anti-fighting replies
· ‎Matching emojis
· ‎Many smart reply patterns/templates
· ‎Prayer-specific fun captions
· ‎Content request waiting message
· ‎Better media request handling
· ‎Better automatic daily reminders
‎
‎Required Render Environment Variables:
‎
‎BOT_TOKEN
‎OPENAI_API_KEY
‎OPENAI_MODEL                  optional
‎
‎ADSGRAM_BLOCK_ID              bot-52042
‎ADSGRAM_TOKEN                 REQUIRED for AdsGram Bot API
‎ADSGRAM_WEBAPP_URL            compatibility
‎
‎Optional:
‎TIMEZONE=Asia/Dhaka
‎PRAYER_CITY=Dhaka
‎PRAYER_COUNTRY=Bangladesh
‎PRAYER_METHOD=1
‎DB_FILE=bot_database.db
‎
‎AUTO_MESSAGES_ENABLED=true
‎STUDY_HOURS=7,10,15,19
‎SPORTS_HOURS=17,21
‎SLEEP_HOUR=23
‎WAKE_HOUR=7
‎WORK_HOURS=9,13,20
‎"""
‎
‎import os
‎import re
‎import time
‎import asyncio
‎import logging
‎import sqlite3
‎import traceback
‎import random
‎from datetime import datetime
‎from html import escape as html_escape
‎
‎import pytz
‎import aiohttp
‎from dotenv import load_dotenv
‎
‎from telegram import (
‎    Update,
‎    InlineKeyboardButton,
‎    InlineKeyboardMarkup,
‎)
‎from telegram.constants import ParseMode
‎from telegram.ext import (
‎    ApplicationBuilder,
‎    CommandHandler,
‎    MessageHandler,
‎    CallbackQueryHandler,
‎    ChatMemberHandler,
‎    ContextTypes,
‎    filters,
‎)
‎
‎============================================================================
‎CONFIGURATION
‎============================================================================
‎
‎load_dotenv()
‎
‎BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
‎
‎OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
‎OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip()
‎
‎ADMIN_IDS = [8721334265]
‎ADMIN_USERNAME = "tomalchowdhury2"
‎
‎Boss identity
‎BOSS_NAME = "TOMAL CHOWDHURY"
‎BOSS_USERNAME = "@tomalchowdhury2"
‎
‎TIMEZONE_NAME = os.getenv(
‎    "TIMEZONE",
‎    "Asia/Dhaka"
‎)
‎
‎try:
‎    TZ = pytz.timezone(TIMEZONE_NAME)
‎except Exception:
‎    TZ = pytz.timezone("Asia/Dhaka")
‎
‎PRAYER_CITY = os.getenv(
‎    "PRAYER_CITY",
‎    "Dhaka"
‎)
‎
‎PRAYER_COUNTRY = os.getenv(
‎    "PRAYER_COUNTRY",
‎    "Bangladesh"
‎)
‎
‎PRAYER_METHOD = os.getenv(
‎    "PRAYER_METHOD",
‎    "1"
‎)
‎
‎DB_FILE = os.getenv(
‎    "DB_FILE",
‎    "bot_database.db"
‎)
‎
‎============================================================================
‎ADSTERRA CONFIGURATION
‎============================================================================
‎
‎ADSTERRA_AD_URL = os.getenv(
‎    "ADSTERRA_AD_URL",
‎    ""
‎).strip()
‎
‎Adsterra is enabled only when a URL is provided.
‎ADSTERRA_ENABLED = bool(ADSTERRA_AD_URL)
‎
‎
‎============================================================================
‎AUTOMATIC NOTIFICATIONS
‎============================================================================
‎
‎AUTO_MESSAGES_ENABLED = os.getenv(
‎    "AUTO_MESSAGES_ENABLED",
‎    "true"
‎).lower() in {
‎    "1",
‎    "true",
‎    "yes",
‎    "on"
‎}
‎
‎
‎def parse_hours(
‎    value,
‎    default
‎):
‎
‎    result = []
‎
‎    for item in (
‎        value.split(",")
‎        if value
‎        else []
‎    ):
‎
‎        try:
‎
‎            h = int(
‎                item.strip()
‎            )
‎
‎            if 0 <= h <= 23:
‎                result.append(h)
‎
‎        except ValueError:
‎            pass
‎
‎    return sorted(
‎        set(result)
‎    ) or default
‎
‎
‎STUDY_HOURS = parse_hours(
‎    os.getenv(
‎        "STUDY_HOURS",
‎        "7,10,15,19"
‎    ),
‎    [7, 10, 15, 19]
‎)
‎
‎SPORTS_HOURS = parse_hours(
‎    os.getenv(
‎        "SPORTS_HOURS",
‎        "17,21"
‎    ),
‎    [17, 21]
‎)
‎
‎WORK_HOURS = parse_hours(
‎    os.getenv(
‎        "WORK_HOURS",
‎        "9,13,20"
‎    ),
‎    [9, 13, 20]
‎)
‎
‎try:
‎    SLEEP_HOUR = int(
‎        os.getenv(
‎            "SLEEP_HOUR",
‎            "23"
‎        )
‎    )
‎except Exception:
‎    SLEEP_HOUR = 23
‎
‎try:
‎    WAKE_HOUR = int(
‎        os.getenv(
‎            "WAKE_HOUR",
‎            "7"
‎        )
‎    )
‎except Exception:
‎    WAKE_HOUR = 7
‎
‎============================================================================
‎LOGGING
‎============================================================================
‎
‎logging.basicConfig(
‎    format=(
‎        "%(asctime)s - "
‎        "%(name)s - "
‎        "%(levelname)s - "
‎        "%(message)s"
‎    ),
‎    level=logging.INFO,
‎)
‎
‎logger = logging.getLogger(
‎    "telegram_bot"
‎)
‎
‎============================================================================
‎OPENAI
‎============================================================================
‎
‎openai_client = None
‎
‎if OPENAI_API_KEY:
‎
‎    try:
‎
‎        from openai import AsyncOpenAI
‎
‎        openai_client = AsyncOpenAI(
‎            api_key=OPENAI_API_KEY
‎        )
‎
‎        logger.info(
‎            "OpenAI client configured successfully."
‎        )
‎
‎    except Exception as e:
‎
‎        logger.warning(
‎            "Could not initialize OpenAI client: %s",
‎            e
‎        )
‎
‎else:
‎
‎    logger.warning(
‎        "OPENAI_API_KEY is missing."
‎    )
‎
‎============================================================================
‎DATABASE
‎============================================================================
‎
‎
‎def get_db():
‎
‎    conn = sqlite3.connect(
‎        DB_FILE,
‎        check_same_thread=False
‎    )
‎
‎    conn.row_factory = sqlite3.Row
‎
‎    return conn
‎
‎
‎def db_execute(
‎    query,
‎    params=(),
‎    fetchone=False,
‎    fetch=False,
‎    commit=True
‎):
‎
‎    with get_db() as conn:
‎
‎        cur = conn.cursor()
‎
‎        cur.execute(
‎            query,
‎            params
‎        )
‎
‎        if commit:
‎            conn.commit()
‎
‎        if fetchone:
‎
‎            row = cur.fetchone()
‎
‎            return (
‎                dict(row)
‎                if row
‎                else None
‎            )
‎
‎        if fetch:
‎
‎            return [
‎                dict(r)
‎                for r in cur.fetchall()
‎            ]
‎
‎        return cur.lastrowid
‎
‎
‎def now_str():
‎
‎    return datetime.now(
‎        TZ
‎    ).strftime(
‎        "%Y-%m-%d %H:%M:%S"
‎    )
‎
‎
‎def init_db():
‎
‎    with get_db() as conn:
‎
‎        cur = conn.cursor()
‎
‎        cur.execute("""
‎        CREATE TABLE IF NOT EXISTS users (
‎            user_id INTEGER PRIMARY KEY,
‎            first_name TEXT,
‎            last_name TEXT,
‎            username TEXT,
‎            joined_at TEXT
‎        )
‎        """)
‎
‎        cur.execute("""
‎        CREATE TABLE IF NOT EXISTS chats (
‎            chat_id INTEGER PRIMARY KEY,
‎            chat_type TEXT,
‎            title TEXT,
‎            username TEXT,
‎            created_at TEXT,
‎            notification_enabled INTEGER DEFAULT 1
‎        )
‎        """)
‎
‎        cur.execute("""
‎        CREATE TABLE IF NOT EXISTS contents (
‎            id INTEGER PRIMARY KEY AUTOINCREMENT,
‎            title TEXT NOT NULL,
‎            media_type TEXT NOT NULL,
‎            file_id TEXT NOT NULL,
‎            category TEXT DEFAULT 'other',
‎            views INTEGER DEFAULT 0,
‎            added_by INTEGER,
‎            created_at TEXT
‎        )
‎        """)
‎
‎        cur.execute("""
‎        CREATE TABLE IF NOT EXISTS messages (
‎            id INTEGER PRIMARY KEY AUTOINCREMENT,
‎            chat_id INTEGER,
‎            user_id INTEGER,
‎            role TEXT,
‎            content TEXT,
‎            created_at TEXT
‎        )
‎        """)
‎
‎        cur.execute("""
‎        CREATE TABLE IF NOT EXISTS bot_state (
‎            key TEXT PRIMARY KEY,
‎            value TEXT
‎        )
‎        """)
‎
‎        cur.execute("""
‎        CREATE TABLE IF NOT EXISTS categories (
‎            key TEXT PRIMARY KEY,
‎            label TEXT NOT NULL,
‎            aliases TEXT DEFAULT '',
‎            sort_order INTEGER DEFAULT 0,
‎            active INTEGER DEFAULT 1,
‎            created_at TEXT
‎        )
‎        """)
‎
‎        cur.execute(
‎            "PRAGMA table_info(contents)"
‎        )
‎
‎        content_cols = [
‎            c[1]
‎            for c in cur.fetchall()
‎        ]
‎
‎        if "views" not in content_cols:
‎
‎            cur.execute(
‎                "ALTER TABLE contents "
‎                "ADD COLUMN views INTEGER DEFAULT 0"
‎            )
‎
‎        cur.execute(
‎            "PRAGMA table_info(chats)"
‎        )
‎
‎        chat_cols = [
‎            c[1]
‎            for c in cur.fetchall()
‎        ]
‎
‎        if "notification_enabled" not in chat_cols:
‎
‎            cur.execute(
‎                "ALTER TABLE chats "
‎                "ADD COLUMN notification_enabled "
‎                "INTEGER DEFAULT 1"
‎            )
‎
‎        conn.commit()
‎
‎    seed_default_categories()
‎
‎    logger.info(
‎        "Database initialized."
‎    )
‎
‎
‎def save_user(user):
‎
‎    if not user:
‎        return
‎
‎    db_execute(
‎        """
‎        INSERT INTO users(
‎            user_id,
‎            first_name,
‎            last_name,
‎            username,
‎            joined_at
‎        )
‎        VALUES (?, ?, ?, ?, ?)
‎
‎        ON CONFLICT(user_id)
‎        DO UPDATE SET
‎            first_name=excluded.first_name,
‎            last_name=excluded.last_name,
‎            username=excluded.username
‎        """,
‎        (
‎            user.id,
‎            user.first_name or "",
‎            user.last_name or "",
‎            user.username or "",
‎            now_str(),
‎        )
‎    )
‎
‎
‎def save_chat(chat):
‎
‎    if not chat:
‎        return
‎
‎    db_execute(
‎        """
‎        INSERT INTO chats(
‎            chat_id,
‎            chat_type,
‎            title,
‎            username,
‎            created_at,
‎            notification_enabled
‎        )
‎        VALUES (?, ?, ?, ?, ?, 1)
‎
‎        ON CONFLICT(chat_id)
‎        DO UPDATE SET
‎            chat_type=excluded.chat_type,
‎            title=excluded.title,
‎            username=excluded.username
‎        """,
‎        (
‎            chat.id,
‎            chat.type,
‎            chat.title or "",
‎            chat.username or "",
‎            now_str(),
‎        )
‎    )
‎
‎
‎def set_chat_notifications(
‎    chat_id,
‎    enabled
‎):
‎
‎    db_execute(
‎        """
‎        UPDATE chats
‎        SET notification_enabled=?
‎        WHERE chat_id=?
‎        """,
‎        (
‎            1 if enabled else 0,
‎            chat_id,
‎        )
‎    )
‎
‎
‎def get_notification_chats():
‎
‎    return db_execute(
‎        """
‎        SELECT
‎            chat_id,
‎            chat_type,
‎            title
‎        FROM chats
‎        WHERE notification_enabled=1
‎        ORDER BY chat_id
‎        """,
‎        fetch=True
‎    )
‎
‎
‎def save_message(
‎    chat_id,
‎    user_id,
‎    role,
‎    content
‎):
‎
‎    db_execute(
‎        """
‎        INSERT INTO messages(
‎            chat_id,
‎            user_id,
‎            role,
‎            content,
‎            created_at
‎        )
‎        VALUES (?, ?, ?, ?, ?)
‎        """,
‎        (
‎            chat_id,
‎            user_id,
‎            role,
‎            content,
‎            now_str(),
‎        )
‎    )
‎
‎
‎def get_history(
‎    chat_id,
‎    limit=6
‎):
‎
‎    rows = db_execute(
‎        """
‎        SELECT role, content
‎        FROM messages
‎        WHERE chat_id=?
‎        ORDER BY id DESC
‎        LIMIT ?
‎        """,
‎        (
‎            chat_id,
‎            limit
‎        ),
‎        fetch=True
‎    )
‎
‎    return (
‎        rows[::-1]
‎        if rows
‎        else []
‎    )
‎
‎
‎def get_state(key):
‎
‎    row = db_execute(
‎        """
‎        SELECT value
‎        FROM bot_state
‎        WHERE key=?
‎        """,
‎        (key,),
‎        fetchone=True
‎    )
‎
‎    return (
‎        row["value"]
‎        if row
‎        else None
‎    )
‎
‎
‎def set_state(
‎    key,
‎    value
‎):
‎
‎    db_execute(
‎        """
‎        INSERT INTO bot_state(
‎            key,
‎            value
‎        )
‎        VALUES (?, ?)
‎
‎        ON CONFLICT(key)
‎        DO UPDATE SET
‎            value=excluded.value
‎        """,
‎        (
‎            key,
‎            str(value),
‎        )
‎    )
‎
‎============================================================================
‎DEFAULT CATEGORIES
‎============================================================================
‎
‎DEFAULT_CATEGORIES = [
‎
‎    ("romantic", "❤️ রোমান্টিক", "রোমান্টিক,romantic,প্রেমের"),
‎    ("comedy", "😂 কমেডি", "কমেডি,comedy,হাসির"),
‎    ("family", "👨‍👩‍👧 ফ্যামিলি", "ফ্যামিলি,family,পারিবারিক"),
‎    ("emotional", "😭 ইমোশনাল", "ইমোশনাল,emotional"),
‎    ("love", "💖 ভালোবাসা", "ভালোবাসা,love"),
‎    ("sad", "💔 দুঃখের", "দুঃখের,sad,দুঃখ"),
‎    ("action", "💥 অ্যাকশন", "অ্যাকশন,action"),
‎    ("thriller", "🕵️ থ্রিলার", "থ্রিলার,thriller"),
‎    ("horror", "👻 ভৌতিক", "ভৌতিক,horror,ভূতের"),
‎    ("mystery", "🔍 রহস্য", "রহস্য,mystery"),
‎    ("adventure", "🏕️ অ্যাডভেঞ্চার", "অ্যাডভেঞ্চার,adventure"),
‎    ("family_drama", "🏠 পারিবারিক নাটক", "পারিবারিক নাটক"),
‎    ("village", "🌾 গ্রামের গল্প", "গ্রামের গল্প,গ্রাম,গ্রাম্য"),
‎    ("city", "🏙️ শহরের গল্প", "শহরের গল্প,শহর"),
‎    ("school", "🏫 স্কুল জীবন", "স্কুল,school,স্কুল জীবন"),
‎    ("college", "🎓 কলেজ জীবন", "কলেজ,college,কলেজ জীবন"),
‎    ("office", "💼 অফিস/কাজ", "অফিস,office,কাজের"),
‎    ("friendship", "🤝 বন্ধুত্ব", "বন্ধুত্ব,friendship"),
‎    ("couple", "💑 কাপল", "কাপল,couple"),
‎    ("breakup", "💔 ব্রেকআপ", "ব্রেকআপ,breakup"),
‎    ("marriage", "💍 বিয়ে", "বিয়ে,বিবাহ,marriage"),
‎    ("social", "🌍 সামাজিক", "সামাজিক,social"),
‎    ("islamic", "🕌 ইসলামিক", "ইসলামিক,islamic"),
‎    ("motivational", "🔥 মোটিভেশনাল", "মোটিভেশনাল,motivational"),
‎    ("educational", "📚 শিক্ষামূলক", "শিক্ষামূলক,educational"),
‎    ("funny", "🤣 হাসির", "হাসির,funny"),
‎    ("viral", "🚀 ভাইরাল", "ভাইরাল,viral"),
‎    ("trending", "🔥 ট্রেন্ডিং", "ট্রেন্ডিং,trending"),
‎    ("short", "⚡ শর্ট ভিডিও", "শর্ট,short,শর্ট ভিডিও"),
‎    ("tiktok", "📱 TikTok", "tiktok,TikTok"),
‎    ("reels", "🎞️ Reels", "reels,Reels"),
‎    ("youtube", "▶️ YouTube", "youtube,YouTube"),
‎    ("movie", "🎬 মুভি", "মুভি,movie,সিনেমা"),
‎    ("webseries", "📺 ওয়েব সিরিজ", "ওয়েব সিরিজ,webseries,series"),
‎    ("natok", "🎭 বাংলা নাটক", "নাটক,natok,drama,বাংলা নাটক"),
‎    ("music", "🎵 গান", "গান,music,song"),
‎    ("romantic_song", "🎶 রোমান্টিক গান", "রোমান্টিক গান"),
‎    ("sad_song", "🎼 স্যাড গান", "স্যাড গান"),
‎    ("folk", "🪕 লোকগান", "লোকগান,folk"),
‎    ("islamic_song", "🕋 ইসলামিক গান", "ইসলামিক গান"),
‎    ("gazal", "🎤 গজল", "গজল,gazal"),
‎    ("nasheed", "🕌 নাশিদ", "নাশিদ,nasheed"),
‎    ("quran", "📖 কুরআন", "কুরআন,quran"),
‎    ("waz", "🎙️ ওয়াজ", "ওয়াজ,waz"),
‎    ("dua", "🤲 দোয়া", "দোয়া,dua"),
‎    ("hadith", "📜 হাদিস", "হাদিস,hadith"),
‎    ("ramadan", "🌙 রমজান", "রমজান,ramadan"),
‎    ("eid", "🌙 ঈদ", "ঈদ,eid"),
‎    ("dance", "💃 ডান্স", "ডান্স,dance"),
‎    ("sports", "🏆 স্পোর্টস", "স্পোর্টস,sports"),
‎    ("cricket", "🏏 ক্রিকেট", "ক্রিকেট,cricket"),
‎    ("football", "⚽ ফুটবল", "ফুটবল,football"),
‎    ("wrestling", "🤼 রেসলিং", "রেসলিং,wrestling"),
‎    ("badminton", "🏸 ব্যাডমিন্টন", "ব্যাডমিন্টন,badminton"),
‎    ("tennis", "🎾 টেনিস", "টেনিস,tennis"),
‎    ("basketball", "🏀 বাস্কেটবল", "বাস্কেটবল,basketball"),
‎    ("volleyball", "🏐 ভলিবল", "ভলিবল,volleyball"),
‎    ("news", "📰 নিউজ", "নিউজ,news"),
‎    ("technology", "💻 টেকনোলজি", "টেক,technology,tech"),
‎    ("ai", "🤖 AI", "ai,এআই"),
‎    ("programming", "👨‍💻 প্রোগ্রামিং", "প্রোগ্রামিং,programming,coding"),
‎    ("gaming", "🎮 গেমিং", "গেমিং,gaming"),
‎    ("mobile_games", "📱 মোবাইল গেম", "মোবাইল গেম"),
‎    ("pc_games", "🖥️ PC গেম", "pc game,কম্পিউটার গেম"),
‎    ("travel", "✈️ ভ্রমণ", "ভ্রমণ,travel"),
‎    ("nature", "🌿 প্রকৃতি", "প্রকৃতি,nature"),
‎    ("rain", "🌧️ বৃষ্টি", "বৃষ্টি,rain"),
‎    ("winter", "❄️ শীত", "শীত,winter,শীতের"),
‎    ("summer", "☀️ গরম", "গরম,summer,hot,heat"),
‎    ("storm", "⛈️ ঝড়", "ঝড়,storm"),
‎    ("food", "🍔 খাবার", "খাবার,food"),
‎    ("cooking", "👨‍🍳 রান্না", "রান্না,cooking"),
‎    ("recipe", "🍳 রেসিপি", "রেসিপি,recipe"),
‎    ("street_food", "🌮 স্ট্রিট ফুড", "স্ট্রিট ফুড"),
‎    ("animals", "🐾 প্রাণী", "প্রাণী,animals"),
‎    ("pets", "🐶 পোষা প্রাণী", "পোষা প্রাণী,pets"),
‎    ("kids", "🧒 শিশুদের", "শিশু,kids"),
‎    ("cartoon", "🧸 কার্টুন", "কার্টুন,cartoon"),
‎    ("anime", "⚔️ Anime", "anime"),
‎    ("documentary", "🎥 ডকুমেন্টারি", "ডকুমেন্টারি,documentary"),
‎    ("history", "🏛️ ইতিহাস", "ইতিহাস,history"),
‎    ("science", "🔬 বিজ্ঞান", "বিজ্ঞান,science"),
‎    ("space", "🚀 মহাকাশ", "মহাকাশ,space"),
‎    ("health", "🩺 স্বাস্থ্য", "স্বাস্থ্য,health"),
‎    ("fitness", "💪 ফিটনেস", "ফিটনেস,fitness"),
‎    ("lifestyle", "✨ লাইফস্টাইল", "লাইফস্টাইল,lifestyle"),
‎    ("fashion", "👕 ফ্যাশন", "ফ্যাশন,fashion"),
‎    ("beauty", "💄 বিউটি", "বিউটি,beauty"),
‎    ("cars", "🚗 গাড়ি", "গাড়ি,cars"),
‎    ("bikes", "🏍️ বাইক", "বাইক,bikes"),
‎    ("motivation", "🔥 অনুপ্রেরণা", "অনুপ্রেরণা,motivation"),
‎    ("quotes", "💬 উক্তি", "উক্তি,quotes"),
‎    ("poetry", "📝 কবিতা", "কবিতা,poetry"),
‎    ("story", "📖 গল্প", "গল্প,story"),
‎    ("jokes", "🤣 জোকস", "জোকস,jokes"),
‎    ("memes", "😂 মিম", "মিম,memes"),
‎    ("status", "💫 স্ট্যাটাস", "স্ট্যাটাস,status"),
‎    ("romantic_status", "💞 প্রেমের স্ট্যাটাস", "প্রেমের স্ট্যাটাস"),
‎    ("sad_status", "💔 স্যাড স্ট্যাটাস", "স্যাড স্ট্যাটাস"),
‎    ("funny_status", "😂 ফানি স্ট্যাটাস", "ফানি স্ট্যাটাস"),
‎    ("love_story", "💖 প্রেমের গল্প", "প্রেমের গল্প"),
‎    ("school_story", "🏫 স্কুলের গল্প", "স্কুলের গল্প"),
‎    ("village_story", "🌾 গ্রামের গল্প", "গ্রামের গল্প"),
‎    ("ghost_story", "👻 ভূতের গল্প", "ভূতের গল্প"),
‎    ("crime", "🔎 ক্রাইম", "ক্রাইম,crime"),
‎    ("detective", "🕵️ গোয়েন্দা", "গোয়েন্দা,detective"),
‎    ("political", "🏛️ রাজনৈতিক", "রাজনৈতিক,political"),
‎    ("business", "💰 ব্যবসা", "ব্যবসা,business"),
‎    ("earning", "💵 আয়", "আয়,earning"),
‎    ("freelancing", "💻 ফ্রিল্যান্সিং", "ফ্রিল্যান্সিং,freelancing"),
‎    ("jobs", "💼 চাকরি", "চাকরি,jobs"),
‎    ("study", "📚 পড়াশোনা", "পড়াশোনা,study"),
‎    ("exam", "📝 পরীক্ষা", "পরীক্ষা,exam"),
‎    ("english", "🇬🇧 ইংরেজি", "ইংরেজি,english"),
‎    ("bangla", "🇧🇩 বাংলা", "বাংলা,bangla"),
‎    ("language", "🗣️ ভাষা", "ভাষা,language"),
‎    ("photography", "📷 ফটোগ্রাফি", "ফটোগ্রাফি,photography"),
‎    ("cinematic", "🎞️ সিনেমাটিক", "সিনেমাটিক,cinematic"),
‎    ("editing", "✂️ এডিটিং", "এডিটিং,editing"),
‎    ("creator", "🎥 ক্রিয়েটর", "ক্রিয়েটর,creator"),
‎    ("youtube_tips", "▶️ YouTube Tips", "youtube tips"),
‎    ("telegram", "✈️ Telegram", "telegram"),
‎    ("apps", "📱 Apps", "অ্যাপ,apps"),
‎    ("internet", "🌐 Internet", "ইন্টারনেট,internet"),
‎    ("other", "📂 অন্যান্য", "অন্যান্য,other"),
‎]
‎
‎
‎def seed_default_categories():
‎
‎    count_row = db_execute(
‎        "SELECT COUNT(*) AS c FROM categories",
‎        fetchone=True
‎    )
‎
‎    count = (
‎        count_row["c"]
‎        if count_row
‎        else 0
‎    )
‎
‎Important:
‎Existing database categories are NEVER deleted.
‎    if count > 0:
‎        return
‎
‎    for index, item in enumerate(
‎        DEFAULT_CATEGORIES
‎    ):
‎
‎        key, label, aliases = item
‎
‎        db_execute(
‎            """
‎            INSERT OR IGNORE INTO categories(
‎                key,
‎                label,
‎                aliases,
‎                sort_order,
‎                active,
‎                created_at
‎            )
‎            VALUES (?, ?, ?, ?, 1, ?)
‎            """,
‎            (
‎                key,
‎                label,
‎                aliases,
‎                index,
‎                now_str(),
‎            )
‎        )
‎
‎
‎def get_categories(
‎    active_only=True
‎):
‎
‎    if active_only:
‎
‎        return db_execute(
‎            """
‎            SELECT *
‎            FROM categories
‎            WHERE active=1
‎            ORDER BY sort_order ASC, key ASC
‎            """,
‎            fetch=True
‎        )
‎
‎    return db_execute(
‎        """
‎        SELECT *
‎        FROM categories
‎        ORDER BY sort_order ASC, key ASC
‎        """,
‎        fetch=True
‎    )
‎
‎
‎def get_category(key):
‎
‎    return db_execute(
‎        """
‎        SELECT *
‎        FROM categories
‎        WHERE key=?
‎        """,
‎        (key,),
‎        fetchone=True
‎    )
‎
‎
‎def category_exists(key):
‎
‎    return bool(
‎        get_category(key)
‎    )
‎
‎
‎def get_category_labels():
‎
‎    rows = get_categories()
‎
‎    return {
‎        row["key"]: row["label"]
‎        for row in rows
‎    }
‎
‎============================================================================
‎TEXT HELPERS
‎============================================================================
‎
‎
‎def normalize_text(text):
‎
‎    if not text:
‎        return ""
‎
‎    text = str(text).lower()
‎
‎    text = re.sub(
‎        r"[^\w\s\u0980-\u09FF]",
‎        " ",
‎        text
‎    )
‎
‎    text = re.sub(
‎        r"\s+",
‎        " ",
‎        text
‎    )
‎
‎    return text.strip()
‎
‎
‎def clean_category_key(value):
‎
‎    value = normalize_text(
‎        value
‎    )
‎
‎    value = re.sub(
‎        r"\s+",
‎        "_",
‎        value
‎    )
‎
‎    value = re.sub(
‎        r"[^a-z0-9_\u0980-\u09FF]",
‎        "",
‎        value
‎    )
‎
‎    return value[:50]
‎
‎============================================================================
‎CATEGORY INTENT
‎============================================================================
‎
‎
‎def category_alias_map():
‎
‎    result = {}
‎
‎    rows = get_categories()
‎
‎    for row in rows:
‎
‎        key = row["key"]
‎
‎        result[
‎            normalize_text(key)
‎        ] = key
‎
‎        label_clean = normalize_text(
‎            row["label"]
‎        )
‎
‎        if label_clean:
‎
‎            result[
‎                label_clean
‎            ] = key
‎
‎        aliases = row["aliases"] or ""
‎
‎        for alias in aliases.split(","):
‎
‎            alias = normalize_text(
‎                alias
‎            )
‎
‎            if alias:
‎
‎                result[
‎                    alias
‎                ] = key
‎
‎Direct aliases
‎    result.update({
‎        "নাটক": "natok",
‎        "নাটক দেন": "natok",
‎        "নাটক দাও": "natok",
‎        "drama": "natok",
‎        "natok": "natok",
‎
‎        "গান": "music",
‎        "গান দেন": "music",
‎        "গান দাও": "music",
‎        "song": "music",
‎        "music": "music",
‎
‎        "ভিডিও": "other",
‎        "ভিডিও দেন": "other",
‎        "ভিডিও দাও": "other",
‎        "video": "other",
‎
‎        "মুভি": "movie",
‎        "movie": "movie",
‎
‎        "শীত": "winter",
‎        "শীতের": "winter",
‎        "শীতের ভিডিও": "winter",
‎
‎        "বৃষ্টি": "rain",
‎        "বৃষ্টি ভিডিও": "rain",
‎
‎        "গরম": "summer",
‎
‎        "ক্রিকেট": "cricket",
‎        "ফুটবল": "football",
‎        "স্পোর্টস": "sports",
‎
‎        "ইসলামিক": "islamic",
‎        "গজল": "gazal",
‎        "ওয়াজ": "waz",
‎
‎        "ভাইরাল": "viral",
‎        "ট্রেন্ডিং": "trending",
‎
‎        "কার্টুন": "cartoon",
‎        "গেম": "gaming",
‎        "গেমিং": "gaming",
‎
‎        "ভ্রমণ": "travel",
‎        "প্রকৃতি": "nature",
‎        "খাবার": "food",
‎        "রান্না": "cooking",
‎    })
‎
‎    return result
‎
‎
‎def detect_category_intent(text):
‎
‎    norm = normalize_text(
‎        text
‎    )
‎
‎    if not norm:
‎        return None
‎
‎    aliases = category_alias_map()
‎
‎    if norm in aliases:
‎
‎        return aliases[norm]
‎
‎    candidates = sorted(
‎        aliases.items(),
‎        key=lambda x: len(x[0]),
‎        reverse=True
‎    )
‎
‎    for alias, key in candidates:
‎
‎        if len(alias) < 2:
‎            continue
‎
‎        if re.search(
‎            r"(^|\s)"
· ‎re.escape(alias)
· ‎r"($|\s)",
‎            norm
‎        ):
‎            return key
‎
‎    for alias, key in candidates:
‎
‎        if (
‎            len(alias) >= 3
‎            and alias in norm
‎        ):
‎            return key
‎
‎    return None
‎
‎
‎def is_category_request(text):
‎
‎    norm = normalize_text(
‎        text
‎    )
‎
‎    category = detect_category_intent(
‎        norm
‎    )
‎
‎    if not category:
‎        return False
‎
‎    request_words = [
‎        "আছে",
‎        "দাও",
‎        "দেন",
‎        "চাই",
‎        "লাগবে",
‎        "পাঠাও",
‎        "পাঠান",
‎        "দেও",
‎        "দিবে",
‎        "দিবেন",
‎        "দেখাও",
‎        "দেখান",
‎        "দেখতে",
‎        "কি আছে",
‎        "কিছু আছে",
‎        "ভিডিও",
‎        "কন্টেন্ট",
‎        "content",
‎        "show",
‎        "give",
‎        "please",
‎    ]
‎
‎    if any(
‎        word in norm
‎        for word in request_words
‎    ):
‎        return True
‎
‎    category_row = get_category(
‎        category
‎    )
‎
‎    return bool(category_row)
‎
‎============================================================================
‎CATEGORY BUTTONS
‎============================================================================
‎
‎CATEGORY_PAGE_SIZE = 12
‎
‎
‎def category_buttons(
‎    page=0,
‎    prefix="usercat"
‎):
‎
‎    categories = get_categories()
‎
‎    total_pages = max(
‎        1,
‎        (
‎            len(categories)
· ‎CATEGORY_PAGE_SIZE
· ‎1
‎        )
‎        // CATEGORY_PAGE_SIZE
‎    )
‎
‎    page = max(
‎        0,
‎        min(
‎            page,
‎            total_pages - 1
‎        )
‎    )
‎
‎    start = (
‎        page * CATEGORY_PAGE_SIZE
‎    )
‎
‎    items = categories[
‎        start:
‎        start + CATEGORY_PAGE_SIZE
‎    ]
‎
‎    buttons = []
‎
‎    for i in range(
‎        0,
‎        len(items),
‎        2
‎    ):
‎
‎        row = []
‎
‎        for item in items[
‎            i:i + 2
‎        ]:
‎
‎            row.append(
‎                InlineKeyboardButton(
‎                    item["label"],
‎                    callback_data=(
‎                        f"{prefix}:"
‎                        f"{item['key']}"
‎                    )
‎                )
‎            )
‎
‎        buttons.append(row)
‎
‎    nav = []
‎
‎    if page > 0:
‎
‎        nav.append(
‎            InlineKeyboardButton(
‎                "⬅️ Back",
‎                callback_data=(
‎                    f"{prefix}_page:"
‎                    f"{page - 1}"
‎                )
‎            )
‎        )
‎
‎    if page < total_pages - 1:
‎
‎        nav.append(
‎            InlineKeyboardButton(
‎                "🔽 See More",
‎                callback_data=(
‎                    f"{prefix}_page:"
‎                    f"{page + 1}"
‎                )
‎            )
‎        )
‎
‎    if nav:
‎        buttons.append(nav)
‎
‎    return (
‎        buttons,
‎        page,
‎        total_pages
‎    )
‎
‎
‎def category_prompt(
‎    prefix="usercat",
‎    page=0,
‎    heading="📂 Category"
‎):
‎
‎    buttons, page, total_pages = (
‎        category_buttons(
‎            page,
‎            prefix
‎        )
‎    )
‎
‎    total = len(
‎        get_categories()
‎    )
‎
‎    if prefix == "usercat":
‎
‎        text = (
‎            f"{heading}\n\n"
‎            "অবশ্যই! 👇\n"
‎            "আপনার প্রয়োজনীয় Category "
‎            "নির্বাচন করুন।\n\n"
‎            f"📂 মোট Category: {total}\n"
‎            f"📄 Page {page + 1}/{total_pages}"
‎        )
‎
‎    else:
‎
‎        text = (
‎            "🏷️ Category নির্বাচন করুন\n\n"
‎            "ভিডিওটি কোন Category-তে রাখতে "
‎            "চান সেটি নির্বাচন করুন। 👇\n\n"
‎            f"📂 মোট Category: {total}\n"
‎            f"📄 Page {page + 1}/{total_pages}"
‎        )
‎
‎    return (
‎        text,
‎        InlineKeyboardMarkup(
‎            buttons
‎        )
‎    )
‎
‎============================================================================
‎CONTENT
‎============================================================================
‎
‎
‎def detect_category(title):
‎
‎    t = normalize_text(
‎        title
‎    )
‎
‎    if any(
‎        x in t
‎        for x in [
‎            "নাটক",
‎            "drama",
‎            "natok"
‎        ]
‎    ):
‎        return "natok"
‎
‎    if any(
‎        x in t
‎        for x in [
‎            "গান",
‎            "song",
‎            "audio",
‎            "গজল",
‎            "music"
‎        ]
‎    ):
‎        return "music"
‎
‎    if any(
‎        x in t
‎        for x in [
‎            "মুভি",
‎            "movie",
‎            "cinema",
‎            "ফিল্ম"
‎        ]
‎    ):
‎        return "movie"
‎
‎    if any(
‎        x in t
‎        for x in [
‎            "ডান্স",
‎            "dance"
‎        ]
‎
