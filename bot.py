# ==========================================
# TELEGRAM CONTENT BOT
# Songs • Dramas • Movies • Videos • Photos
# Admin uploads content -> Users search by name
# ==========================================

import os
import json
import logging
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ==========================================
# CONFIG
# ==========================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DB_FILE = "database.json"

# ==========================================
# LOGGING
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# ==========================================
# DATABASE
# ==========================================

def load_db():
    if not os.path.exists(DB_FILE):
        data = {
            "contents": [],
            "users": []
        }

        save_db(data)
        return data

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "contents": [],
            "users": []
        }


def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


db = load_db()

# ==========================================
# STATES
# ==========================================

WAITING_CONTENT_NAME = 1
WAITING_CONTENT_FILE = 2

# ==========================================
# HELPERS
# ==========================================

def is_admin(update: Update):

    if not update.effective_user:
        return False

    return update.effective_user.id == ADMIN_ID


def add_user(user):

    if not user:
        return

    user_id = user.id

    for u in db["users"]:
        if u["id"] == user_id:
            return

    db["users"].append({
        "id": user_id,
        "name": user.full_name,
        "username": user.username or ""
    })

    save_db(db)


def get_content_type(message):

    if message.video:
        return "video"

    if message.photo:
        return "photo"

    if message.audio:
        return "audio"

    if message.document:
        return "document"

    return "unknown"


# ==========================================
# START
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    add_user(update.effective_user)

    text = (
        "👋 Welcome!\n\n"
        "🎬 আমাদের Content Bot-এ স্বাগতম।\n\n"
        "🔎 কোনো গান, নাটক, মুভি বা ভিডিও খুঁজতে "
        "শুধু তার নাম লিখুন।\n\n"
        "📌 উদাহরণ:\n"
        "• একটা গান দেন\n"
        "• ABC নাটক\n"
        "• XYZ মুভি\n"
        "• Tomar Jonno গান\n\n"
        "💡 সরাসরি কনটেন্টের নাম লিখলেও সার্চ হবে।"
    )

    if is_admin(update):
        text += (
            "\n\n👑 আপনি Admin।\n"
            "/admin দিয়ে Admin Panel খুলুন।"
        )

    await update.message.reply_text(text)


# ==========================================
# ADMIN PANEL
# ==========================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )
        return

    text = (
        "👑 ADMIN PANEL\n\n"
        "📥 নতুন Content যোগ করতে:\n"
        "/add\n\n"
        "📊 মোট Content দেখতে:\n"
        "/stats\n\n"
        "📋 সব Content দেখতে:\n"
        "/contents\n\n"
        "🗑️ Content Delete করতে:\n"
        "/delete ID\n\n"
        "ℹ️ Bot বন্ধ করতে:\n"
        "/cancel"
    )

    await update.message.reply_text(text)


# ==========================================
# ADD CONTENT - STEP 1
# ==========================================

async def add_content(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):
        await update.message.reply_text(
            "❌ আপনি Admin নন।"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🎬 নতুন Content যোগ করছি।\n\n"
        "প্রথমে Content-এর নাম লিখুন।\n\n"
        "উদাহরণ:\n"
        "Tomar Jonno গান"
    )

    return WAITING_CONTENT_NAME


# ==========================================
# ADD CONTENT - STEP 2
# ==========================================

async def receive_content_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return ConversationHandler.END

    name = update.message.text.strip()

    if not name:
        await update.message.reply_text(
            "❌ নাম খালি রাখা যাবে না। আবার লিখুন।"
        )
        return WAITING_CONTENT_NAME

    context.user_data["content_name"] = name

    await update.message.reply_text(
        "✅ নাম নেওয়া হয়েছে:\n"
        f"🎬 {name}\n\n"
        "এখন ভিডিও / ছবি / অডিও / ফাইল পাঠান।"
    )

    return WAITING_CONTENT_FILE


# ==========================================
# ADD CONTENT - STEP 3
# ==========================================

async def receive_content_file(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):
        return ConversationHandler.END

    message = update.message

    content_type = get_content_type(message)

    if content_type == "unknown":

        await message.reply_text(
            "❌ এই ধরনের ফাইল গ্রহণ করা হচ্ছে না।\n\n"
            "🎬 Video\n"
            "🖼️ Photo\n"
            "🎵 Audio\n"
            "📁 Document পাঠান।"
        )

        return WAITING_CONTENT_FILE

    name = context.user_data.get(
        "content_name",
        "Unknown"
    )

    file_id = None

    if message.video:
        file_id = message.video.file_id

    elif message.photo:
        file_id = message.photo[-1].file_id

    elif message.audio:
        file_id = message.audio.file_id

    elif message.document:
        file_id = message.document.file_id

    # নতুন ID
    content_id = len(db["contents"]) + 1

    content = {
        "id": content_id,
        "name": name,
        "type": content_type,
        "file_id": file_id,
        "added_by": update.effective_user.id
    }

    db["contents"].append(content)

    save_db(db)

    await message.reply_text(
        "✅ Content সফলভাবে Save হয়েছে!\n\n"
        f"🆔 ID: {content_id}\n"
        f"🎬 Name: {name}\n"
        f"📁 Type: {content_type}\n\n"
        "👤 এখন User নাম লিখে এই Content খুঁজে পাবে।"
    )

    context.user_data.clear()

    return ConversationHandler.END


# ==========================================
# CANCEL
# ==========================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Operation Cancelled."
    )

    return ConversationHandler.END


# ==========================================
# SEARCH CONTENT
# ==========================================

async def search_content(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    add_user(update.effective_user)

    if not update.message or not update.message.text:
        return

    query = update.message.text.strip().lower()

    if not query:
        return

    # Commands ignore
    if query.startswith("/"):
        return

    matches = []

    for content in db["contents"]:

        name = content.get("name", "").lower()

        if query in name or name in query:
            matches.append(content)

    if not matches:

        await update.message.reply_text(
            "😔 দুঃখিত, এই নামে কোনো Content পাওয়া যায়নি।\n\n"
            "🔎 আবার সঠিক নাম লিখে চেষ্টা করুন।"
        )

        return

    await update.message.reply_text(
        "👋 Welcome!\n"
        "⏳ একটু অপেক্ষা করুন, দিচ্ছি..."
    )

    for content in matches:

        try:

            file_id = content["file_id"]
            name = content["name"]

            caption = (
                f"🎬 {name}\n\n"
                f"📁 Type: {content['type']}"
            )

            if content["type"] == "video":

                await update.message.reply_video(
                    video=file_id,
                    caption=caption
                )

            elif content["type"] == "photo":

                await update.message.reply_photo(
                    photo=file_id,
                    caption=caption
                )

            elif content["type"] == "audio":

                await update.message.reply_audio(
                    audio=file_id,
                    caption=caption
                )

            elif content["type"] == "document":

                await update.message.reply_document(
                    document=file_id,
                    caption=caption
                )

        except Exception as e:

            logger.error(
                f"Content send error: {e}"
            )

            await update.message.reply_text(
                "❌ Content পাঠাতে সমস্যা হয়েছে।"
            )

    await update.message.reply_text(
        "আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝"
    )


# ==========================================
# STATS
# ==========================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return

    total_content = len(db["contents"])
    total_users = len(db["users"])

    await update.message.reply_text(
        "📊 BOT STATISTICS\n\n"
        f"👥 Total Users: {total_users}\n"
        f"🎬 Total Content: {total_content}"
    )


# ==========================================
# CONTENT LIST
# ==========================================

async def contents(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return

    if not db["contents"]:

        await update.message.reply_text(
            "📭 এখনো কোনো Content যোগ করা হয়নি।"
        )

        return

    text = "📋 CONTENT LIST\n\n"

    for content in db["contents"]:

        text += (
            f"🆔 {content['id']}\n"
            f"🎬 {content['name']}\n"
            f"📁 {content['type']}\n\n"
        )

    await update.message.reply_text(text)


# ==========================================
# DELETE CONTENT
# ==========================================

async def delete_content(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return

    if not context.args:

        await update.message.reply_text(
            "ব্যবহার করুন:\n"
            "/delete ID\n\n"
            "উদাহরণ:\n"
            "/delete 3"
        )

        return

    try:
        content_id = int(context.args[0])
    except ValueError:

        await update.message.reply_text(
            "❌ ID অবশ্যই সংখ্যা হতে হবে।"
        )

        return

    found = None

    for content in db["contents"]:

        if content["id"] == content_id:
            found = content
            break

    if not found:

        await update.message.reply_text(
            "❌ এই ID-এর কোনো Content পাওয়া যায়নি।"
        )

        return

    db["contents"].remove(found)

    save_db(db)

    await update.message.reply_text(
        "🗑️ Content Delete হয়েছে!\n\n"
        f"🆔 ID: {content_id}\n"
        f"🎬 {found['name']}"
    )


# ==========================================
# ADMIN TEST
# ==========================================

async def admin_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_admin(update):

        await update.message.reply_text(
            "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
        )

        return

    await update.message.reply_text(
        "👑 Admin Test Successful!\n\n"
        "✅ Bot\n"
        "✅ Admin ID\n"
        "✅ Database\n"
        "সব ঠিক আছে।"
    )


# ==========================================
# ERROR HANDLER
# ==========================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )


# ==========================================
# MAIN
# ==========================================

def main():

    if not BOT_TOKEN:

        print(
            "❌ BOT_TOKEN পাওয়া যায়নি। "
            ".env ফাইলে BOT_TOKEN বসান।"
        )

        return

    if not ADMIN_ID:

        print(
            "❌ ADMIN_ID পাওয়া যায়নি। "
            ".env ফাইলে ADMIN_ID বসান।"
        )

        return

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------
    # ADD CONTENT CONVERSATION
    # --------------------------------------

    add_conversation = ConversationHandler(

        entry_points=[
            CommandHandler(
                "add",
                add_content
            )
        ],

        states={

            WAITING_CONTENT_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_content_name
                )
            ],

            WAITING_CONTENT_FILE: [
                MessageHandler(
                    filters.ALL & ~filters.COMMAND,
                    receive_content_file
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel
            )
        ]
    )

    application.add_handler(
        add_conversation
    )

    # --------------------------------------
    # COMMANDS
    # --------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin
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
            "contents",
            contents
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
            "admin_test",
            admin_test
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    # --------------------------------------
    # USER SEARCH
    # --------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            search_content
        )
    )

    # --------------------------------------
    # ERROR
    # --------------------------------------

    application.add_error_handler(
        error_handler
    )

    print("===================================")
    print("🤖 Telegram Bot Started")
    print("===================================")

    application.run_polling(
        drop_pending_updates=True
    )


# ==========================================
# START BOT
# ==========================================

if __name__ == "__main__":
    main()
