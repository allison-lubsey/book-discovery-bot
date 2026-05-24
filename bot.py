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
from screenshot_extractor import extract_books_from_screenshot, SUPPORTED_EXTENSIONS
from notion_handler import save_book_to_notion, book_exists_in_notion
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
        "Share a TikTok or Instagram link *or a screenshot* and I'll:\n"
        "• Extract any books mentioned in the caption or visible in the image\n"
        "• Save them to your Notion database\n"
        "• Send you an Ntfy notification\n\n"
        "Paste a link or send a photo to get started!",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["help"])
def handle_help(message):
    bot.reply_to(
        message,
        "📖 *How it works:*\n\n"
        "1. Paste a TikTok or Instagram link *or send a screenshot*\n"
        "2. I extract book titles & authors from the caption, comments, or image\n"
        "3. Books are saved to your Notion DB\n"
        "4. You get an Ntfy push notification\n\n"
        "📌 *Can't find books automatically?*\n"
        "If no books are detected, I'll save the entry to Notion so you "
        "can look up the titles later.\n\n"
        "*Supported platforms (links):*\n"
        "• TikTok videos & short links\n"
        "• Instagram posts & Reels\n\n"
        "*Supported image formats (screenshots):*\n"
        "• JPG / JPEG, PNG, WebP\n"
        "• Send as a photo _or_ as a file attachment\n\n"
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
        bot.reply_to(message, "Please send a TikTok or Instagram link, or share a screenshot.")
        return

    # Must be a supported platform
    if not any(host in text.lower() for host in SUPPORTED_HOSTS):
        bot.reply_to(
            message,
            "❌ Only TikTok and Instagram links are supported.\n"
            "Please share a link from one of those platforms, or send a screenshot.",
        )
        return

    # Spin up a thread so the webhook response isn't blocked
    thread = threading.Thread(target=_process_link, args=(message, text), daemon=True)
    thread.start()


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    """Handle images sent as compressed Telegram photos."""
    user_id = str(message.from_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    # Telegram compresses all photos to JPEG
    photo = message.photo[-1]   # last element is the largest size
    file_info = bot.get_file(photo.file_id)
    image_data = bot.download_file(file_info.file_path)

    thread = threading.Thread(
        target=_process_screenshot,
        args=(message, image_data, "image/jpeg"),
        daemon=True,
    )
    thread.start()


@bot.message_handler(content_types=["document"])
def handle_document(message):
    """Handle images sent as uncompressed file attachments."""
    user_id = str(message.from_user.id)
    if ALLOWED_USER_ID and user_id != ALLOWED_USER_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return

    doc  = message.document
    mime = (doc.mime_type or "").lower()

    # Canonical set of accepted MIME types derived from SUPPORTED_EXTENSIONS
    accepted_mimes = set(SUPPORTED_EXTENSIONS.values())  # image/jpeg, image/png, image/webp

    if mime not in accepted_mimes:
        if mime.startswith("image/"):
            bot.reply_to(
                message,
                "❌ Unsupported image format.\n"
                "Please send a JPG, PNG, or WebP file.",
            )
        # Silently ignore non-image documents (PDFs, ZIPs, etc.)
        return

    file_info  = bot.get_file(doc.file_id)
    image_data = bot.download_file(file_info.file_path)

    thread = threading.Thread(
        target=_process_screenshot,
        args=(message, image_data, mime),
        daemon=True,
    )
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

        # ── Step 2b: No books found — save link for later ────────────────
        if not books:
            has_comments = "Comments:" in content
            save_book_to_notion({"title": "📌 Review Later", "author": "Unknown"}, url)
            edit(
                f"📌 *No books detected — link saved to Notion for later review.*\n\n"
                f"_Comments fetched: {'✅' if has_comments else '❌ (none returned)'}_\n\n"
                f"Open your Notion database to find the link and look up the book titles manually.",
                parse_mode="Markdown",
            )
            send_notification(
                NTFY_TOPIC,
                title="📌 Link Saved for Later",
                message=f"No books detected — saved link for manual review:\n{url}",
                tags=["bookmark"],
            )
            return

        # ── Step 3: Enrich from Google Books, then save to Notion ───────
        edit(f"💾 Found {len(books)} book(s)! Looking up details & saving…")

        saved:   list[dict] = []
        skipped: list[dict] = []   # books already in Notion

        for book in books:
            gb = get_book_info(book["title"], book["author"])

            # Fill in author when Groq couldn't find one
            if book["author"].lower() == "unknown" and gb["author"]:
                logger.info(
                    "Author resolved via Google Books: '%s' → '%s'",
                    book["title"], gb["author"],
                )
                book["author"] = gb["author"]

            if book_exists_in_notion(book["title"], book["author"]):
                skipped.append(book)
            elif save_book_to_notion(book, url):
                saved.append(book)

        # ── Step 4: Report results ───────────────────────────────────────
        if saved:
            lines     = "\n".join(f"📖 *{b['title']}* — _{b['author']}_" for b in saved)
            dupe_note = ""
            if skipped:
                dupe_note = "\n\n📚 *Already in Notion:* " + ", ".join(
                    f"_{b['title']}_" for b in skipped
                )
            edit(
                f"✅ *Saved {len(saved)} book(s) to Notion!*\n\n{lines}{dupe_note}",
                parse_mode="Markdown",
            )
            notif_body = "\n".join(f"• {b['title']} by {b['author']}" for b in saved)
            send_notification(
                NTFY_TOPIC,
                title=f"📚 {len(saved)} Book(s) Saved!",
                message=notif_body,
                tags=["books", "white_check_mark"],
            )
        elif skipped:
            lines = "\n".join(f"📚 *{b['title']}* — _{b['author']}_" for b in skipped)
            edit(
                f"📚 *Already in your Notion library!*\n\n{lines}",
                parse_mode="Markdown",
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


def _process_screenshot(message, image_data: bytes, media_type: str):
    """
    Screenshot pipeline: vision extract → Google Books enrich → save → notify.

    Mirrors _process_link but starts from an image instead of a scraped URL.
    """
    chat_id    = message.chat.id
    status_msg = bot.reply_to(message, "⏳ Analyzing screenshot for books…")

    def edit(text, **kwargs):
        try:
            bot.edit_message_text(text, chat_id, status_msg.message_id, **kwargs)
        except Exception:
            pass  # ignore if already deleted / unchanged

    try:
        # ── Step 1: Extract books via Claude vision ───────────────────────
        books = extract_books_from_screenshot(image_data, media_type)

        # ── Step 1b: No books found — save placeholder for later review ──
        if not books:
            save_book_to_notion({"title": "📌 Review Later", "author": "Unknown"}, None)
            edit(
                "📌 *No books detected in screenshot — entry saved to Notion for later review.*\n\n"
                "Open your Notion database to add the book title manually.",
                parse_mode="Markdown",
            )
            send_notification(
                NTFY_TOPIC,
                title="📌 Screenshot Saved for Later",
                message="No books detected in screenshot — saved for manual review.",
                tags=["bookmark"],
            )
            return

        # ── Step 2: Enrich from Google Books, then save to Notion ─────────
        edit(f"💾 Found {len(books)} book(s)! Looking up details & saving…")

        saved:   list[dict] = []
        skipped: list[dict] = []   # books already in Notion

        for book in books:
            gb = get_book_info(book["title"], book["author"])

            # Fill in author when vision couldn't find one
            if book["author"].lower() == "unknown" and gb["author"]:
                logger.info(
                    "Author resolved via Google Books: '%s' → '%s'",
                    book["title"], gb["author"],
                )
                book["author"] = gb["author"]

            if book_exists_in_notion(book["title"], book["author"]):
                skipped.append(book)
            elif save_book_to_notion(book, None):   # no source URL for screenshots
                saved.append(book)

        # ── Step 3: Report results ─────────────────────────────────────────
        if saved:
            lines     = "\n".join(f"📖 *{b['title']}* — _{b['author']}_" for b in saved)
            dupe_note = ""
            if skipped:
                dupe_note = "\n\n📚 *Already in Notion:* " + ", ".join(
                    f"_{b['title']}_" for b in skipped
                )
            edit(
                f"✅ *Saved {len(saved)} book(s) to Notion!*\n\n{lines}{dupe_note}",
                parse_mode="Markdown",
            )
            notif_body = "\n".join(f"• {b['title']} by {b['author']}" for b in saved)
            send_notification(
                NTFY_TOPIC,
                title=f"📚 {len(saved)} Book(s) Saved!",
                message=notif_body,
                tags=["books", "white_check_mark"],
            )
        elif skipped:
            lines = "\n".join(f"📚 *{b['title']}* — _{b['author']}_" for b in skipped)
            edit(
                f"📚 *Already in your Notion library!*\n\n{lines}",
                parse_mode="Markdown",
            )
        else:
            edit("⚠️ Books were detected but could not be saved to Notion. Check your Notion config.")

    except Exception as exc:
        logger.exception("Unexpected error processing screenshot")
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
