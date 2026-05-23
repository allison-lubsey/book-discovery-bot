"""
ntfy_client.py
--------------
Sends push notifications via ntfy.sh (free, no account required).

Usage:
    send_notification("my-topic", "Title", "Body text", tags=["books"])

Ntfy priority levels:
    1 = min  |  2 = low  |  3 = default  |  4 = high  |  5 = max/urgent
"""

import logging
import requests

logger = logging.getLogger(__name__)

_NTFY_BASE = "https://ntfy.sh"


def send_notification(
    topic: str,
    title: str,
    message: str,
    tags: list[str] | None = None,
    priority: int = 3,
) -> bool:
    """
    Send a push notification to an Ntfy topic.

    Args:
        topic:    Your Ntfy topic name (from NTFY_TOPIC env var).
        title:    Short notification title.
        message:  Notification body.
        tags:     List of emoji shortcodes, e.g. ["books", "white_check_mark"].
        priority: 1–5 (default 3).

    Returns:
        True if the notification was sent successfully, False otherwise.
    """
    if not topic:
        logger.warning("Ntfy topic is empty – skipping notification.")
        return False

    # HTTP headers must be latin-1 safe — strip any emoji from the title
    safe_title = title.encode("latin-1", errors="ignore").decode("latin-1").strip()

    headers = {
        "Title":    safe_title or "Book Bot",
        "Priority": str(priority),
        "Content-Type": "text/plain",
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        resp = requests.post(
            f"{_NTFY_BASE}/{topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Ntfy notification sent to topic '%s': %s", topic, title)
        return True

    except requests.RequestException as exc:
        logger.error("Ntfy notification failed (topic '%s'): %s", topic, exc)
        return False
