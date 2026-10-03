import os
import logging
from datetime import time
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN")

# এখানে তোমার Telegram Admin-এর numeric User ID পরে বসাবে
ADMIN_ID = 0

# Admin-এর Telegram profile link
ADMIN_LINK = "https://t.me/tomalchowdhury2"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    text = f"""
👋 আসসালামু আলাইকুম {user.first_name}!

🤖 আমি তোমাদের Group Assistant Bot।

📋 Available Commands:

/start - Bot শুরু
/help - সাহায্য
/menu - মেনু
/admin - Admin-এর সাথে যোগাযোগ
/namaz - নামাজের সময়
/movie - মুভি
/natok - নাটক
/song - গান
/video - ভিডিও
/photo - ছবি

🆘 সাহায্য প্রয়োজন হলে:
/admin ব্যবহার করো।
"""

    await update.message.reply_text(text)


# =========================
# HELP
# =========================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
🆘 সাহায্য

Bot-এর কোনো সমস্যা হলে অথবা কোনো বিষয়ে সাহায্য লাগলে:

👉 /admin

ব্যবহার করো।

Admin তোমার সাথে যোগাযোগ করবে।
"""

    await update.message.reply_text(text)


# =========================
# MENU
# =========================

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
📋 BOT MENU

🎬 /movie
📺 /natok
🎵 /song
🎥 /video
🖼️ /photo

🕌 /namaz
🆘 /admin
ℹ️ /help
"""

    await update.message.reply_text(text)


# =========================
# ADMIN CONTACT
# =========================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = f"""
🆘 Admin-এর সাথে যোগাযোগ

সাহায্য লাগলে নিচের লিংকে ক্লিক করুন:

👉 {ADMIN_LINK}
"""

    await update.message.reply_text(text)


# =========================
# MEDIA COMMANDS
# =========================

async def movie(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎬 মুভি সেকশন\n\n"
        "Admin অনুমোদিত মুভির তথ্য/মিডিয়া এখানে যুক্ত করা যাবে।"
    )


async def natok(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "📺 নাটক সেকশন\n\n"
        "Admin অনুমোদিত নাটকের তথ্য/মিডিয়া এখানে যুক্ত করা যাবে।"
    )


async def song(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎵 গান সেকশন\n\n"
        "Admin অনুমোদিত গান/অডিও এখানে যুক্ত করা যাবে।"
    )


async def video(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎥 ভিডিও সেকশন\n\n"
        "Admin অনুমোদিত ভিডিও এখানে যুক্ত করা যাবে।"
    )


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🖼️ ছবি সেকশন\n\n"
        "Admin অনুমোদিত ছবি এখানে যুক্ত করা যাবে।"
    )


# =========================
# NAMAZ
# =========================

async def namaz(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
🕌 আজকের নামাজের সময়

📍 Location সেট করা হয়নি।

পরের ধাপে আমরা তোমার এলাকার
অনুযায়ী স্বয়ংক্রিয় নামাজের সময়
যোগ করব।

ফজর 🌅
যোহর ☀️
আসর 🌇
মাগরিব 🌆
এশা 🌙
"""

    await update.message.reply_text(text)


# =========================
# WELCOME MESSAGE
# =========================

async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):

    for member in update.message.new_chat_members:

        name = member.first_name

        await update.message.reply_text(
            f"""
🎉 Welcome {name}!

🤖 আমাদের Group Assistant-এ
তোমাকে স্বাগতম।

📋 /menu লিখে Bot-এর Menu দেখুন।

🆘 সাহায্য লাগলে /admin ব্যবহার করুন।
"""
        )


# =========================
# AUTO REPLY
# =========================

async def auto_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    message = update.message.text.lower().strip()

    replies = {

        "hi": "👋 হ্যালো! কেমন আছেন?",
        "hello": "👋 হ্যালো! স্বাগতম।",
        "হাই": "👋 হাই! কেমন আছেন?",
        "হ্যালো": "👋 হ্যালো! স্বাগতম।",
        "assalamualaikum": "ওয়ালাইকুমুস সালাম 🌸",
        "আসসালামু আলাইকুম": "ওয়ালাইকুমুস সালাম 🌸",
        "কি খবর": "আলহামদুলিল্লাহ, ভালো আছি 😊",
        "কেমন আছো": "আলহামদুলিল্লাহ ভালো আছি 🤖",
        "help": "🆘 সাহায্যের জন্য /admin ব্যবহার করুন।",

    }

    if message in replies:

        await update.message.reply_text(
            replies[message]
        )


# =========================
# REMINDER
# =========================

async def study_reminder(context: ContextTypes.DEFAULT_TYPE):

    chat_id = context.job.data

    await context.bot.send_message(
        chat_id=chat_id,
        text="📚 পড়ার সময় হয়েছে!\n\n"
             "এখন কিছুক্ষণ মন দিয়ে পড়াশোনা করুন। 💪"
    )


async def food_reminder(context: ContextTypes.DEFAULT_TYPE):

    chat_id = context.job.data

    await context.bot.send_message(
        chat_id=chat_id,
        text="🍚 খাবারের সময় হয়েছে!\n\n"
             "সময়মতো খাবার খেয়ে নিন। ❤️"
    )


# =========================
# ADMIN CHECK
# =========================

def is_admin(update: Update):

    if not update.effective_user:
        return False

    return update.effective_user.id == ADMIN_ID


# =========================
# ADMIN TEST
# =========================

async def admin_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return

    await update.message.reply_text(
        "👑 Admin Control সক্রিয় আছে।"
    )


# =========================
# BOT STARTUP
# =========================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN পাওয়া যায়নি। Render Environment Variables-এ BOT_TOKEN যোগ করুন।"
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("menu", menu)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    application.add_handler(
        CommandHandler("movie", movie)
    )

    application.add_handler(
        CommandHandler("natok", natok)
    )

    application.add_handler(
        CommandHandler("song", song)
    )

    application.add_handler(
        CommandHandler("video", video)
    )

    application.add_handler(
        CommandHandler("photo", photo)
    )

    application.add_handler(
        CommandHandler("namaz", namaz)
    )

    application.add_handler(
        CommandHandler("admintest", admin_test)
    )

    # Welcome

    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            welcome
        )
    )

    # Auto Reply

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            auto_reply
        )
    )

    print("🤖 Telegram Bot is running...")

    application.run_polling()


if __name__ == "__main__":
    main()
