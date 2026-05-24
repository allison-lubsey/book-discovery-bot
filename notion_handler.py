"""
notion_handler.py
-----------------
Saves book entries to a Notion database.

Expected Notion database schema
────────────────────────────────
Property name   │ Notion type
────────────────┼────────────
Title           │ Title        (built-in, required)
Author          │ Rich Text
Source URL      │ URL
Date Saved      │ Date
Status          │ Select       (options: Want to Read, Reading, Read)
Cover Image     │ URL
"""

import os
import logging
from datetime import datetime, timezone
from notion_client import Client
from notion_client.errors import APIResponseError

logger = logging.getLogger(__name__)

_notion: Client | None = None


def _get_client() -> Client:
    global _notion
    if _notion is None:
        _notion = Client(auth=os.environ["NOTION_API_KEY"])
    return _notion


DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")


def save_book_to_notion(book: dict, source_url: str | None = None) -> bool:
    """
    Create a new page in the Notion books database.

    Args:
        book:       Dict with keys 'title', 'author', and optionally 'cover_url'.
        source_url: The original TikTok/Instagram URL, or None for screenshots.

    Returns:
        True on success, False on failure.
    """
    title     = (book.get("title") or "Unknown Title").strip()
    author    = (book.get("author") or "Unknown").strip()
    cover_url = book.get("cover_url")
    today     = datetime.now(timezone.utc).date().isoformat()  # "YYYY-MM-DD"

    # ── Build properties payload ──────────────────────────────────────────
    properties: dict = {
        "Title": {
            "title": [{"text": {"content": title}}]
        },
        "Author": {
            "rich_text": [{"text": {"content": author}}]
        },
        "Date Saved": {
            "date": {"start": today}
        },
        "Status": {
            "select": {"name": "Want to Read"}
        },
    }

    # Only include Source URL when we actually have one (screenshots have none)
    if source_url:
        properties["Source URL"] = {"url": source_url}

    if cover_url:
        properties["Cover Image"] = {"url": cover_url}

    # ── Build page payload ────────────────────────────────────────────────
    page_payload: dict = {
        "parent":     {"database_id": DATABASE_ID},
        "properties": properties,
    }

    # Set the Notion page cover image for a visual card layout
    if cover_url:
        page_payload["cover"] = {
            "type":     "external",
            "external": {"url": cover_url},
        }

    # ── Create the page ───────────────────────────────────────────────────
    try:
        notion = _get_client()
        page = notion.pages.create(**page_payload)
        logger.info(
            "Saved '%s' to Notion (page id: %s)",
            title,
            page.get("id", "?"),
        )
        return True

    except APIResponseError as exc:
        logger.error(
            "Notion API error saving '%s': %s (status %s)",
            title,
            exc.body,
            exc.status,
        )
        return False
    except Exception as exc:
        logger.error("Unexpected Notion error saving '%s': %s", title, exc)
        return False
