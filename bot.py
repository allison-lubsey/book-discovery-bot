"""
Book Discovery Bot
------------------
Telegram webhook bot that extracts books from TikTok/Instagram captions
using Groq AI and saves them to a Notion database.
"""

import os
import logging
import threading
from flask import Flask, request, abort
import telebot
from dotenv import load_dotenv

from social_scraper import fetch_post_content
from book_extractor import extract_books
from notion_handler import save_book_to_notion
from google_books import get_book_info
from ntfy_client import send_notification

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────
TOKEN            = os.environ["TELEGRAM_BOT_TOKEN"]
NTFY_TOPIC       = os.environ["NTFY_TOPIC"]
RENDER_URL       = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
ALLOWED_USER_ID  = os.environ.get("TELEGRAM_USER_ID", "")   # optional – leave blank to allow anyone

SUPPORTED_HOSTS  = ("tiktok.com", "vm.tiktok.com", "instagram.com", "instagr.am")

# ── Setup ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# Flask routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def health():
    """Health-check endpoint – keeps Render alive via UptimeRobot."""
    return "📚 Book Discovery Bot is running!", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive updates from Telegram."""
    if request.content_type != "application/json":
        abort(403)
    update = telebot.types.Update.de_json(request.get_data(as_text=True))
    bot.process_new_updates([update])
    return "", 200


@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """
    Visit this URL once after deploying to register the webhook with Telegram.
    e.g. https://your-app.onrender.com/set_webhook
    """
    if not RENDER_URL:
        return "RENDER_EXTERNAL_URL env var not set.", 500
    webhook_url = f"{RENDER_URL}/webhook"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    return f"✅ Webhook set to: {webhook_url}", 200


# ══════════════════════════════════════════════════════════════════════════════
# Telegram bot handlers
# ══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.reply_to(
        message,
        "📚 *Book Discovery Bot*\n\n"
        "Share a TikTok or Instagram link and I'll:\n"
        "• Extract any books mentioned in the caption\n"
        "• Save them to your Notion database\n"
        "• Send you an Ntfy notification\n\n"
        "Just paste a link to get started!",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["help"])
def handle_help(message):
    bot.reply_to(
        message,
        "📖 *How it works:*\n\n"
        "1. Paste a TikTok or Instagram link\n"
        "2. I extract book titles & authors from the caption\n"
        "3. Books are saved to your Notion DB\n"
        "4. You get an Ntfy push notification\n\n"
        "*Supported platforms:*\n"
        "• TikTok videos & short links\n"
        "• Instagram posts & Reels\n\n"
        "*Commands:*\n"
        "/start – Welcome message\n"
        "/help  – This message",
        parse_mode="Markdown",
    )


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_message(message):
    text = message.text.strip()
    user_id = str(message.from_user.id)

    # Optional: restrict to a single user
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    # Must be a URL
    if not text.startswith(("http://", "https://")):
        bot.reply_to(message, "Please send a TikTok or Instagram link.")
        return

    # Must be a supported platform
    if not any(host in text.lower() for host in SUPPORTED_HOSTS):
        bot.reply_to(
            message,
            "❌ Only TikTok and Instagram links are supported.\n"
            "Please share a link from one of those platforms.",
        )
        return

    # Spin up a thread so the webhook response isn't blocked
    thread = threading.Thread(target=_process_link, args=(message, text), daemon=True)
    thread.start()


# ══════════════════════════════════════════════════════════════════════════════
# Core processing (runs in background thread)
# ══════════════════════════════════════════════════════════════════════════════

def _process_link(message, url: str):
    """Full pipeline: scrape → extract → save → notify."""
    chat_id = message.chat.id
    status_msg = bot.reply_to(message, "⏳ Fetching post content…")

    def edit(text, **kwargs):
        try:
            bot.edit_message_text(text, chat_id, status_msg.message_id, **kwargs)
        except Exception:
            pass  # ignore if already deleted / unchanged

    try:
        # ── Step 1: Scrape caption ───────────────────────────────────────
        content = fetch_post_content(url)

        if not content:
            edit(
                "❌ Could not fetch this post.\n"
                "It may be private, deleted, or the platform blocked the request."
            )
            send_notification(
                NTFY_TOPIC,
                title="📭 Fetch Failed",
                message=f"Could not fetch content from:\n{url}",
                tags=["warning"],
            )
            return

        # ── Step 2: Extract books via Groq ───────────────────────────────
        edit("🤖 Analyzing caption for books…")
        books = extract_books(content)

        if not books:
            has_comments = "Comments:" in content
            preview = content[:500] + "…" if len(content) > 500 else content
            edit(
                f"📭 *No books found.*\n"
                f"_Comments included: {'✅' if has_comments else '❌ (none fetched)'}_\n\n"
                f"_Content preview:_\n`{preview}`",
                parse_mode="Markdown",
            )
            send_notification(
                NTFY_TOPIC,
                title="📭 No Books Found",
                message=f"No books detected in:\n{url}",
                tags=["books"],
            )
            return

        # ── Step 3: Enrich from Google Books, then save to Notion ───────
        edit(f"💾 Found {len(books)} book(s)! Looking up details & saving…")

        saved = []
        for book in books:
            gb = get_book_info(book["title"], book["author"])
            book["cover_url"] = gb["cover_url"]

            # Fill in author when Groq couldn't find one
            if book["author"].lower() == "unknown" and gb["author"]:
                logger.info(
                    "Author resolved via Google Books: '%s' → '%s'",
                    book["title"], gb["author"],
                )
                book["author"] = gb["author"]

            if save_book_to_notion(book, url):
                saved.append(book)

        # ── Step 4: Report results ───────────────────────────────────────
        if saved:
            lines = "\n".join(f"📖 *{b['title']}* — _{b['author']}_" for b in saved)
            edit(
                f"✅ *Saved {len(saved)} book(s) to Notion!*\n\n{lines}",
                parse_mode="Markdown",
            )
            notif_body = "\n".join(f"• {b['title']} by {b['author']}" for b in saved)
            send_notification(
                NTFY_TOPIC,
                title=f"📚 {len(saved)} Book(s) Saved!",
                message=notif_body,
                tags=["books", "white_check_mark"],
            )
        else:
            edit("⚠️ Books were detected but could not be saved to Notion. Check your Notion config.")

    except Exception as exc:
        logger.exception("Unexpected error processing link")
        edit(f"❌ Unexpected error: {exc}")
        send_notification(
            NTFY_TOPIC,
            title="❌ Bot Error",
            message=str(exc),
            tags=["warning"],
        )


# ══════════════════════════════════════════════════════════════════════════════
# Entry point (local dev only – Render uses gunicorn)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info("Starting bot in local dev mode on port %s", port)
    app.run(host="0.0.0.0", port=port, debug=False)
