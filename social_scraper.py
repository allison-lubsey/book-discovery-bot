"""
social_scraper.py
-----------------
Uses yt-dlp to extract caption/description metadata from TikTok and Instagram
posts without downloading any video files.
"""

import logging
import yt_dlp

logger = logging.getLogger(__name__)


def fetch_post_content(url: str) -> str | None:
    """
    Fetch the caption/description of a TikTok or Instagram post.

    Returns a plain-text string with the creator name and caption,
    or None if the content could not be retrieved.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,       # never download the video
        "extract_flat": False,
        "socket_timeout": 20,
        # Mimic a browser to reduce blocks
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Mobile/15E148 Safari/604.1"
            ),
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            logger.warning("yt-dlp returned no info for %s", url)
            return None

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

        content = "\n".join(parts).strip()
        if not content:
            logger.warning("No usable text found in post metadata for %s", url)
            return None

        logger.info("Fetched %d chars of content from %s", len(content), url)
        return content

    except yt_dlp.utils.DownloadError as exc:
        logger.error("yt-dlp download error for %s: %s", url, exc)
        return None
    except Exception as exc:
        logger.error("Unexpected scraper error for %s: %s", url, exc)
        return None
