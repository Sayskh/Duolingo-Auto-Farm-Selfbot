import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.notifications import send_discord_webhook

def test_send_discord_webhook_empty_url():
    assert send_discord_webhook("", "Test") is False
    assert send_discord_webhook(None, "Test") is False

def test_send_discord_webhook_success():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        fields = [{"name": "Learner", "value": "duo_user", "inline": True}]
        result = send_discord_webhook(
            webhook_url="https://discord.com/api/webhooks/dummy",
            title="Summary",
            description="desc",
            color=0x58CC02,
            fields=fields
        )

        assert result is True
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["username"] == "Duolingo Bot"
        assert payload["avatar_url"] == "https://d35aaqx5ub952y.cloudfront.net/images/duo-avatar.png"
        assert len(payload["embeds"]) == 1
        embed = payload["embeds"][0]
        assert embed["title"] == "Summary"
        assert embed["description"] == "desc"
        assert embed["color"] == 0x58CC02
        assert embed["fields"] == fields
        assert "timestamp" in embed
        assert embed["footer"]["text"] == "Duolingo Automation"

def test_send_discord_webhook_exception():
    with patch("requests.post", side_effect=Exception("Network error")):
        result = send_discord_webhook("https://discord.com/api/webhooks/dummy", "Title")
        assert result is False

if __name__ == "__main__":
    test_send_discord_webhook_empty_url()
    test_send_discord_webhook_success()
    test_send_discord_webhook_exception()
    print("All notification tests passed.")
