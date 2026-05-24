"""
google_books.py
---------------
Looks up a book's author name from the Google Books API.
No API key required for basic searches (uses the public endpoint).
GOOGLE_BOOKS_API_KEY is optional — set it to improve rate limits.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY")   # optional – improves rate limits


def get_book_info(title: str, author: str = "") -> dict:
    """
    Search Google Books for the author name of a book.

    Args:
        title:  Book title to search for.
        author: Author name hint (improves accuracy; can be empty or 'Unknown').

    Returns:
        Dict with key:
          'author' – Author name from Google Books, or None if not found.
    """
    empty = {"author": None}

    if not title:
        return empty

    # Build query — wrap in quotes for exact matching
    query = f'intitle:"{title}"'
    if author and author.lower() not in ("", "unknown"):
        query += f' inauthor:"{author}"'

    params: dict = {
        "q":          query,
        "maxResults": 3,
        "printType":  "books",
        "fields":     "items(volumeInfo(title,authors))",
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
            return empty

        for item in items:
            vi           = item.get("volumeInfo", {})
            authors_list = vi.get("authors", [])
            found_author = authors_list[0] if authors_list else None

            if found_author:
                logger.info(
                    "Google Books hit for '%s': author=%s",
                    title, found_author,
                )
                return {"author": found_author}

        logger.info("Google Books: results found but no author for '%s'", title)
        return empty

    except requests.RequestException as exc:
        logger.error("Google Books request failed for '%s': %s", title, exc)
        return empty
    except Exception as exc:
        logger.error("Unexpected Google Books error for '%s': %s", title, exc)
        return empty
