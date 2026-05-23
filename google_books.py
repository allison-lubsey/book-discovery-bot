"""
google_books.py
---------------
Fetches a book cover image URL from the Google Books API.
No API key required for basic searches (uses the public endpoint).
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY")   # optional – improves rate limits


def get_book_cover(title: str, author: str = "") -> str | None:
    """
    Search Google Books for a cover image URL.

    Args:
        title:  Book title to search for.
        author: Author name (improves accuracy; can be empty or 'Unknown').

    Returns:
        A public HTTPS image URL, or None if not found.
    """
    if not title:
        return None

    # Build query — wrap in quotes for exact matching
    query = f'intitle:"{title}"'
    if author and author.lower() not in ("", "unknown"):
        query += f' inauthor:"{author}"'

    params: dict = {
        "q":          query,
        "maxResults": 3,             # fetch 3 so we can pick the best match
        "printType":  "books",
        "fields":     "items(volumeInfo(title,imageLinks))",
        "langRestrict": "en",
    }
    if _API_KEY:
        params["key"] = _API_KEY

    try:
        resp = requests.get(_GOOGLE_BOOKS_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items", [])
        if not items:
            logger.info("Google Books: no results for '%s'", title)
            return None

        for item in items:
            image_links = item.get("volumeInfo", {}).get("imageLinks", {})
            # Prefer highest resolution available
            cover = (
                image_links.get("extraLarge")
                or image_links.get("large")
                or image_links.get("medium")
                or image_links.get("thumbnail")
                or image_links.get("smallThumbnail")
            )
            if cover:
                # Google Books returns http:// — upgrade to https://
                cover = cover.replace("http://", "https://")
                # Remove the edge=curl parameter that adds a page-curl effect
                cover = cover.replace("&edge=curl", "").replace("edge=curl&", "")
                logger.info("Found cover for '%s': %s", title, cover)
                return cover

        logger.info("Google Books: results found but no imageLinks for '%s'", title)
        return None

    except requests.RequestException as exc:
        logger.error("Google Books request failed for '%s': %s", title, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected Google Books error for '%s': %s", title, exc)
        return None
