"""
google_books.py
---------------
Fetches a book cover image URL from the Google Books API.
No API key required for basic searches (uses the public endpoint).

Falls back to Google Custom Search Image API when Google Books returns no cover.
Requires environment variables GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX to be set.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

_GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY")   # optional – improves rate limits

# Google Custom Search Image API (fallback for missing covers)
_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY")
_CSE_CX      = os.environ.get("GOOGLE_CSE_CX")
_CSE_URL     = "https://www.googleapis.com/customsearch/v1"


def _get_cover_from_cse(title: str, author: str = "") -> str | None:
    """
    Fallback: search for a book cover image via Google Custom Search JSON API.

    Args:
        title:  Book title.
        author: Author name (used to narrow the query; may be empty or 'Unknown').

    Returns:
        An image URL string, or None if unavailable / not configured.
    """
    if not _CSE_API_KEY or not _CSE_CX:
        logger.debug("Google CSE not configured — skipping image fallback")
        return None

    query_parts = [title]
    if author and author.lower() not in ("", "unknown"):
        query_parts.append(author)
    query_parts.append("book cover")
    query = " ".join(query_parts)

    params = {
        "key":        _CSE_API_KEY,
        "cx":         _CSE_CX,
        "q":          query,
        "searchType": "image",
        "num":        1,
    }

    try:
        resp = requests.get(_CSE_URL, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if items:
            item = items[0]
            # Prefer Google's cached thumbnail — it's always accessible and
            # won't be blocked by hotlink protection on the source site.
            # Fall back to the direct image link if no thumbnail is present.
            url = (
                item.get("image", {}).get("thumbnailLink")
                or item.get("link")
            )
            logger.info("Google CSE cover fallback for '%s': %s", title, url)
            return url
        logger.info("Google CSE: no image results for '%s'", title)
    except requests.HTTPError as exc:
        # Log only the status code — not the full URL, which contains the API key.
        logger.error(
            "Google CSE request failed for '%s': HTTP %s", title, exc.response.status_code
        )
    except requests.RequestException as exc:
        logger.error("Google CSE request failed for '%s': %s", title, type(exc).__name__)
    except Exception as exc:
        logger.error("Unexpected Google CSE error for '%s': %s", title, exc)

    return None


def get_book_info(title: str, author: str = "") -> dict:
    """
    Search Google Books for a cover image URL *and* author name.

    This is the primary lookup function. It returns both pieces of data in
    a single API call so we don't pay for two round-trips.

    Args:
        title:  Book title to search for.
        author: Author name hint (improves accuracy; can be empty or 'Unknown').

    Returns:
        Dict with keys:
          'cover_url' – HTTPS image URL, or None if not found.
          'author'    – Author name from Google Books, or None if not found.
    """
    empty = {"cover_url": None, "author": None}

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
        # Include authors in the field mask
        "fields":     "items(volumeInfo(title,authors,imageLinks))",
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
            return {
                "cover_url": _get_cover_from_cse(title, author),
                "author":    None,
            }

        for item in items:
            vi           = item.get("volumeInfo", {})
            image_links  = vi.get("imageLinks", {})
            authors_list = vi.get("authors", [])

            # Prefer highest resolution available
            cover = (
                image_links.get("extraLarge")
                or image_links.get("large")
                or image_links.get("medium")
                or image_links.get("thumbnail")
                or image_links.get("smallThumbnail")
            )

            found_author = authors_list[0] if authors_list else None

            if cover or found_author:
                if cover:
                    cover = cover.replace("http://", "https://")
                    cover = cover.replace("&edge=curl", "").replace("edge=curl&", "")
                else:
                    # Author found but no cover — try CSE fallback
                    cover = _get_cover_from_cse(title, found_author or author)

                logger.info(
                    "Google Books hit for '%s': author=%s cover=%s",
                    title, found_author, bool(cover),
                )
                return {"cover_url": cover, "author": found_author}

        logger.info("Google Books: results found but no useful data for '%s'", title)
        return {
            "cover_url": _get_cover_from_cse(title, author),
            "author":    None,
        }

    except requests.RequestException as exc:
        logger.error("Google Books request failed for '%s': %s", title, exc)
        return {"cover_url": _get_cover_from_cse(title, author), "author": None}
    except Exception as exc:
        logger.error("Unexpected Google Books error for '%s': %s", title, exc)
        return empty


def get_book_cover(title: str, author: str = "") -> str | None:
    """Convenience wrapper — returns only the cover URL. (Legacy helper.)"""
    return get_book_info(title, author)["cover_url"]
