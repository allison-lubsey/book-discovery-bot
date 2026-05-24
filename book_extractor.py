"""
book_extractor.py
-----------------
Sends social media caption text to the Groq API (llama-3.1-8b-instant)
and parses the JSON response to return a list of books found.

Also provides extract_books_from_image() which uses Claude vision
(claude-sonnet-4-20250514) as a fallback when the caption alone
yields no results — it inspects the post thumbnail for book covers.
"""

import os
import re
import json
import base64
import logging
import requests as _http
from groq import Groq
import anthropic

logger = logging.getLogger(__name__)
_groq_client: Groq | None = None
_anthropic_client: anthropic.Anthropic | None = None


def _get_client() -> Groq:
    """Lazy-init Groq client (avoids import-time failures in tests)."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _groq_client


def _get_anthropic_client() -> anthropic.Anthropic:
    """Lazy-init Anthropic client (avoids import-time failures in tests)."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a book-detection assistant for a personal reading tracker.

Your ONLY job: identify book titles and author names explicitly mentioned in social media content.
The content may include a caption/description AND comments/replies from the post — treat all sections equally.

Rules:
- Include a book ONLY if its title is clearly stated (exact or near-exact wording).
- Do NOT infer, guess, or include books that are merely implied.
- If an author is not mentioned anywhere in the content, use "Unknown" for the author field.
- Treat both fiction and non-fiction equally.
- Ignore hashtags, emojis, and promotional language unless they contain a clear title.
- PAY SPECIAL ATTENTION to question-and-answer patterns: if a comment asks "what book is this?",
  "book name?", "what's the title?", etc., look for a nearby comment or reply that answers
  with a book title and include that book.
- Return ONLY valid JSON — no explanation, no markdown, no extra text.

Response format (always return this exact shape):
{
  "books": [
    {"title": "Exact Book Title", "author": "Author Full Name"},
    {"title": "Another Title",    "author": "Unknown"}
  ]
}

If no books are found, return exactly:
{"books": []}"""


# ── Main function ─────────────────────────────────────────────────────────────

def extract_books(content: str) -> list[dict]:
    """
    Use Groq (llama-3.1-8b-instant) to extract books from post content.

    Args:
        content: The scraped caption/description text from a social post.

    Returns:
        A list of dicts, each with 'title' and 'author' keys.
        Returns an empty list if none found or on error.
    """
    if not content or not content.strip():
        return []

    # Truncate to avoid token waste — higher limit now that comments are included
    truncated = content[:6000]

    # Debug: log a preview so you can confirm comments/replies are present
    has_comments = "Comments:" in truncated
    logger.info(
        "Sending %d chars to Groq (comments present: %s). Preview: %.200s…",
        len(truncated), has_comments, truncated,
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Extract all book titles and authors from this social media post:\n\n"
                        f"{truncated}"
                    ),
                },
            ],
            temperature=0.1,          # low temp → more deterministic JSON
            max_tokens=512,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        data = json.loads(raw)
        books = data.get("books", [])

        # Validate and sanitise each entry
        validated: list[dict] = []
        for book in books:
            title  = str(book.get("title", "")).strip()
            author = str(book.get("author", "Unknown")).strip() or "Unknown"
            if title:
                validated.append({"title": title, "author": author})

        logger.info("Groq found %d book(s) in caption", len(validated))
        return validated

    except json.JSONDecodeError as exc:
        logger.error("Groq returned invalid JSON: %s", exc)
        return []
    except Exception as exc:
        logger.error("Groq extraction error: %s", exc)
        return []


# ── Vision fallback ───────────────────────────────────────────────────────────

_VISION_PROMPT = (
    'Look at this image carefully. Identify any book covers visible. '
    'For each book, return the title and author in JSON format: '
    '{"books": [{"title": "...", "author": "..."}]}. '
    'If no book covers are visible or you cannot read the title, return {"books": []}.'
)

# Claude Sonnet 4 (claude-sonnet-4-20250514) with vision support.
# Cheaper/faster than Opus; sufficient for book-cover recognition.
_VISION_MODEL = "claude-sonnet-4-20250514"

# MIME types accepted by the Anthropic vision API
_ACCEPTED_MIME = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _extract_json(raw: str) -> dict:
    """
    Parse JSON from a model response that may be wrapped in markdown code fences.
    Falls back to searching for a bare JSON object in the text.
    """
    # 1. Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences (```json ... ``` or ``` ... ```)
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find the first {...} block
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {"books": []}


def extract_books_from_image(image_url: str) -> list[dict]:
    """
    Use Claude vision (claude-sonnet-4-20250514) to identify book covers
    visible in a thumbnail image.

    Args:
        image_url: A publicly accessible URL for the post thumbnail.

    Returns:
        A list of dicts with 'title' and 'author' keys.
        Returns an empty list if no books are found or on any error.
    """
    if not image_url or not image_url.strip():
        return []

    try:
        # ── Fetch the image ──────────────────────────────────────────────────
        resp = _http.get(
            image_url,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/17.0 Mobile/15E148 Safari/604.1"
                )
            },
        )
        resp.raise_for_status()

        # Determine the MIME type; default to image/jpeg if unrecognised
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if content_type not in _ACCEPTED_MIME:
            content_type = "image/jpeg"

        image_data = base64.standard_b64encode(resp.content).decode("utf-8")
        logger.info(
            "Sending %d-byte thumbnail to Claude vision (%s)",
            len(resp.content), content_type,
        )

        # ── Call Claude vision ───────────────────────────────────────────────
        client = _get_anthropic_client()
        response = client.messages.create(
            model=_VISION_MODEL,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": content_type,
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": _VISION_PROMPT,
                        },
                    ],
                }
            ],
        )

        raw = next((b.text for b in response.content if b.type == "text"), "")
        data = _extract_json(raw)
        books = data.get("books", [])

        # Validate and sanitise
        validated: list[dict] = []
        for book in books:
            title  = str(book.get("title", "")).strip()
            author = str(book.get("author", "Unknown")).strip() or "Unknown"
            if title:
                validated.append({"title": title, "author": author})

        logger.info("Claude vision found %d book(s) in thumbnail", len(validated))
        return validated

    except _http.exceptions.RequestException as exc:
        logger.error("Failed to fetch thumbnail image %s: %s", image_url, exc)
        return []
    except anthropic.APIError as exc:
        logger.error("Anthropic vision API error: %s", exc)
        return []
    except Exception as exc:
        logger.error("Unexpected error in extract_books_from_image: %s", exc)
        return []
