"""
book_extractor.py
-----------------
Sends social media caption text to the Groq API (llama-3.1-8b-instant)
and parses the JSON response to return a list of books found.
"""

import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)
_client: Groq | None = None


def _get_client() -> Groq:
    """Lazy-init Groq client (avoids import-time failures in tests)."""
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


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
