"""
screenshot_extractor.py
-----------------------
Sends an image (screenshot) to Claude's vision API (claude-haiku-4-5-20251001)
and extracts any book titles and authors visible in the image.

Mirrors the interface of book_extractor.extract_books() — returns a list of
{"title": ..., "author": ...} dicts, or [] if nothing is found / on error.
"""

import os
import base64
import json
import logging
from anthropic import Anthropic

logger = logging.getLogger(__name__)

_client: Anthropic | None = None

# Maps lowercase file extensions to MIME types accepted by the Anthropic API.
SUPPORTED_EXTENSIONS: dict[str, str] = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "webp": "image/webp",
}

_VISION_MODEL = "claude-haiku-4-5-20251001"

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a book-detection assistant for a personal reading tracker.

Your ONLY job: identify book titles and author names that are clearly visible in the image.
The image may be a screenshot of a social media post, a photo of a bookshelf, a book cover,
or any other image that might display book information.

Rules:
- Include a book ONLY if its title is clearly visible or explicitly stated.
- Do NOT infer, guess, or include books that are merely implied by context.
- If an author name is not visible anywhere in the image, use "Unknown" for the author field.
- Treat both fiction and non-fiction equally.
- Return ONLY valid JSON — no explanation, no markdown code fences, no extra text.

Response format (always return this exact shape):
{
  "books": [
    {"title": "Exact Book Title", "author": "Author Full Name"},
    {"title": "Another Title",    "author": "Unknown"}
  ]
}

If no books are found, return exactly:
{"books": []}"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_client() -> Anthropic:
    """Lazy-init Anthropic client (avoids import-time failures if key is absent)."""
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _parse_json(raw: str) -> dict:
    """
    Parse a JSON response from Claude, tolerating optional markdown code fences.

    Claude is instructed to return bare JSON, but this guard handles the rare
    case where it wraps the output in ```json … ``` anyway.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        # Drop opening fence line (e.g. ```json) and closing fence line
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        raw = "\n".join(lines[start:end]).strip()
    return json.loads(raw)


# ── Main function ─────────────────────────────────────────────────────────────

def extract_books_from_screenshot(image_data: bytes, media_type: str) -> list[dict]:
    """
    Use Claude Haiku vision to extract book titles from an image.

    Args:
        image_data: Raw image bytes (jpg, jpeg, png, or webp).
        media_type: MIME type string, e.g. ``"image/jpeg"`` or ``"image/png"``.

    Returns:
        A list of dicts, each with ``'title'`` and ``'author'`` keys.
        Returns an empty list if no books are found or on any error.
    """
    if not image_data:
        logger.warning("extract_books_from_screenshot called with empty image_data")
        return []

    b64_image = base64.standard_b64encode(image_data).decode("utf-8")
    logger.info(
        "Sending %d-byte image (%s) to Claude vision (%s)",
        len(image_data),
        media_type,
        _VISION_MODEL,
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=_VISION_MODEL,
            max_tokens=512,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type":       "base64",
                                "media_type": media_type,
                                "data":       b64_image,
                            },
                        },
                        {
                            "type": "text",
                            "text": _SYSTEM_PROMPT,
                        },
                    ],
                }
            ],
        )

        raw = response.content[0].text
        logger.debug("Claude vision raw response: %s", raw[:500])

        data  = _parse_json(raw)
        books = data.get("books", [])

        validated: list[dict] = []
        for book in books:
            title  = str(book.get("title", "")).strip()
            author = str(book.get("author", "Unknown")).strip() or "Unknown"
            if title:
                validated.append({"title": title, "author": author})

        logger.info("Claude vision found %d book(s) in screenshot", len(validated))
        return validated

    except json.JSONDecodeError as exc:
        logger.error("Claude vision returned invalid JSON: %s", exc)
        return []
    except Exception as exc:
        logger.error("Claude vision extraction error: %s", exc)
        return []
