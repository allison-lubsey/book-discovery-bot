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


def book_exists_in_notion(title: str, author: str) -> bool:
    """
    Return True if a book with this title AND author already exists in the database.

    Matching rules:
    - Title: Notion's ``title.equals`` filter is case-insensitive, so
      "The Great Gatsby" and "the great gatsby" are treated as the same.
    - Author: normalised to lowercase in Python after fetching results.
    - Same title by *different* authors → NOT a duplicate (two separate books).
    - "📌 Review Later" placeholder entries are never treated as duplicates.
    - Any API error fails open (returns False) so we never silently lose data.
    """
    if not title or title == "📌 Review Later":
        return False

    try:
        notion      = _get_client()
        norm_author = author.strip().lower()

        resp = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "property": "Title",
                "title":    {"equals": title},   # Notion: case-insensitive equals
            },
            page_size=10,   # more than enough for an exact-title match
        )

        for page in resp.get("results", []):
            props = page.get("properties", {})
            rt    = props.get("Author", {}).get("rich_text", [])
            saved_author = (rt[0].get("plain_text", "") if rt else "unknown").strip().lower()
            if saved_author == norm_author:
                logger.info("Duplicate detected: '%s' by '%s'", title, author)
                return True

        return False

    except Exception as exc:
        logger.warning(
            "Duplicate check failed (failing open to avoid data loss): %s", exc
        )
        return False


def save_book_to_notion(book: dict, source_url: str | None = None) -> bool:
    """
    Create a new page in the Notion books database.

    Args:
        book:       Dict with keys 'title' and 'author'.
        source_url: The original TikTok/Instagram URL, or None for screenshots.

    Returns:
        True on success, False on failure.
    """
    title  = (book.get("title") or "Unknown Title").strip()
    author = (book.get("author") or "Unknown").strip()
    today  = datetime.now(timezone.utc).date().isoformat()  # "YYYY-MM-DD"

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

    # ── Build page payload ────────────────────────────────────────────────
    page_payload: dict = {
        "parent":     {"database_id": DATABASE_ID},
        "properties": properties,
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
