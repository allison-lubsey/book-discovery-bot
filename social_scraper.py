"""
social_scraper.py
-----------------
Uses yt-dlp to extract caption/description metadata from TikTok and Instagram
posts without downloading any video files.
"""

import os
import logging
import requests
import yt_dlp

logger = logging.getLogger(__name__)

# Path to a Netscape-format cookies file exported from your browser.
# Set TIKTOK_COOKIES_FILE=/path/to/cookies.txt in your environment / Render vars.
_COOKIES_FILE = os.environ.get("TIKTOK_COOKIES_FILE", "")


def fetch_post_content(url: str) -> dict | None:
    """
    Fetch the caption/description of a TikTok or Instagram post.

    Returns a dict with keys:
      - "text": plain-text string with creator name, caption, and any comments
      - "thumbnail_url": URL of the post thumbnail (may be None)
    Returns None if nothing could be retrieved.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,       # never download the video
        "extract_flat": False,
        "socket_timeout": 20,
        "getcomments": True,         # fetch comment metadata (TikTok/Instagram)
        # Mimic a browser to reduce blocks
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
        },
    }

    # If a cookies file is configured, pass it to yt-dlp so TikTok
    # treats the request as a logged-in browser session — this is the
    # most reliable way to get comments from server/datacenter IPs.
    if _COOKIES_FILE and os.path.isfile(_COOKIES_FILE):
        ydl_opts["cookiefile"] = _COOKIES_FILE
        logger.info("Using TikTok cookies file: %s", _COOKIES_FILE)
    else:
        logger.debug("No TIKTOK_COOKIES_FILE set — comment fetching may be blocked.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            logger.warning("yt-dlp returned no info for %s", url)
            return None

        thumbnail_url: str | None = (info.get("thumbnail") or "").strip() or None

        parts: list[str] = []

        uploader    = (info.get("uploader") or info.get("channel") or "").strip()
        title       = (info.get("title") or "").strip()
        description = (info.get("description") or "").strip()

        if uploader:
            parts.append(f"Creator: {uploader}")

        # TikTok often puts the full caption in description; title is a truncated copy.
        # Instagram puts the caption in description.
        # Avoid adding both if they're identical.
        if title and title != description:
            parts.append(f"Title: {title}")

        if description:
            parts.append(f"Caption: {description}")

        # ── Comments ──────────────────────────────────────────────────────────
        # yt-dlp returns a list of comment dicts when getcomments=True.
        # Each comment may also have a 'replies' list — we flatten those in
        # so that "What book is this?" → reply with title is captured.
        raw_comments: list = info.get("comments") or []
        logger.info("yt-dlp returned %d raw comment(s) for %s", len(raw_comments), url)

        if raw_comments:
            # Flatten top-level comments + their replies into one list
            flat: list[dict] = []
            for c in raw_comments:
                flat.append(c)
                for r in (c.get("replies") or []):
                    flat.append(r)

            # Sort by like_count (most-liked first) and cap total
            flat.sort(key=lambda c: c.get("like_count") or 0, reverse=True)
            top_comments = flat[:40]

            comment_texts = [
                c.get("text", "").strip()
                for c in top_comments
                if c.get("text", "").strip()
            ]
            if comment_texts:
                parts.append(
                    "Comments:\n" + "\n".join(f"• {t}" for t in comment_texts)
                )
                logger.info(
                    "Added %d comment/reply text(s) from %s", len(comment_texts), url
                )
        else:
            logger.warning(
                "No comments returned by yt-dlp for %s — "
                "TikTok may have blocked the request or comments are disabled.",
                url,
            )

        content = "\n".join(parts).strip()
        if not content:
            logger.warning("No usable text found in post metadata for %s", url)
            return None

        logger.info("Fetched %d chars of content from %s", len(content), url)
        return {"text": content, "thumbnail_url": thumbnail_url}

    except yt_dlp.utils.DownloadError as exc:
        logger.error("yt-dlp download error for %s: %s", url, exc)
        logger.info("Trying oEmbed fallback for %s", url)
        return _oembed_fallback(url)
    except Exception as exc:
        logger.error("Unexpected scraper error for %s: %s", url, exc)
        logger.info("Trying oEmbed fallback for %s", url)
        return _oembed_fallback(url)


def _oembed_fallback(url: str) -> dict | None:
    """
    Fallback for when yt-dlp is blocked by TikTok.

    TikTok's public oEmbed endpoint works from server IPs without auth
    and returns the video title/caption + creator name.
    Note: no comments are available via oEmbed.
    """
    # Only TikTok has a reliable oEmbed endpoint
    if "tiktok.com" not in url.lower():
        return None

    try:
        resp = requests.get(
            "https://www.tiktok.com/oembed",
            params={"url": url},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                )
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        parts: list[str] = []
        author        = (data.get("author_name") or "").strip()
        title         = (data.get("title") or "").strip()
        thumbnail_url: str | None = (data.get("thumbnail_url") or "").strip() or None

        if author:
            parts.append(f"Creator: {author}")
        if title:
            parts.append(f"Caption: {title}")

        content = "\n".join(parts).strip()
        if content:
            logger.info(
                "oEmbed fallback succeeded for %s (%d chars, no comments, thumbnail: %s)",
                url, len(content), "yes" if thumbnail_url else "no",
            )
            return {"text": content, "thumbnail_url": thumbnail_url}

        logger.warning("oEmbed returned no usable text for %s", url)
        return None

    except Exception as exc:
        logger.error("oEmbed fallback failed for %s: %s", url, exc)
        return None
