from datetime import datetime, timezone
import logging
import requests

logger = logging.getLogger(__name__)

# ponytail: simple Discord embed; add Slack/Telegram formatting when multi-platform alert is needed
def send_discord_webhook(
    webhook_url: str,
    title: str,
    description: str = "",
    color: int = 0x58CC02,
    fields: list[dict] | None = None,
) -> bool:
    if not webhook_url:
        return False

    payload = {
        "username": "Duolingo Bot",
        "avatar_url": "https://d35aaqx5ub952y.cloudfront.net/images/duo-avatar.png",
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "fields": fields or [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Duolingo Automation"},
            }
        ],
    }

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"Failed to send Discord webhook: {e}")
        return False
