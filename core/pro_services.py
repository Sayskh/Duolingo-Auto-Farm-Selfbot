import json
import logging
from typing import Any

import requests

try:
    from scrapling.fetchers import FetcherSession
except ImportError:
    FetcherSession = None

logger = logging.getLogger("DuoPro")
HAS_SCRAPLING = FetcherSession is not None

class DuolingoProClient:
    """Client for the third-party DuolingoPRO API."""

    API_URL = "https://api.duolingopro.net/request"

    def __init__(self, jwt_token: str):
        self.jwt_token = jwt_token.strip().removeprefix("Bearer ").strip()
        self.headers = {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.duolingo.com",
            "Referer": "https://www.duolingo.com/learn",
        }
        self.use_scrapling = HAS_SCRAPLING

    @staticmethod
    def _parse_stream_response(raw_text: str) -> dict[str, Any]:
        """Parses streamed newline-delimited JSON chunks and returns the latest JSON object."""
        clean = raw_text.strip()
        if not clean:
            return {"status": "error", "raw": ""}
        for line in reversed(clean.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        return {"status": "error", "raw": raw_text}

    def _post_request(self, req_type: str, amount: Any) -> dict[str, Any]:
        """Sends a request payload to https://api.duolingopro.net/request."""
        payload = {
            "type": req_type,
            "amount": amount,
            "version": "3.1BETA.05.2",
            "lang": "en"
        }

        if self.use_scrapling and FetcherSession is not None:
            try:
                with FetcherSession(impersonate="chrome", stealthy_headers=True) as session:
                    resp = session.post(self.API_URL, json=payload, headers=self.headers, timeout=20)
                    body_text = resp.body.decode("utf-8", errors="replace") if hasattr(resp, "body") else getattr(resp, "text", "")
                    return self._parse_stream_response(body_text)
            except Exception as e:
                logger.warning(f"Scrapling failed: {e}, falling back to requests")

        # Fallback using standard requests
        resp = requests.post(self.API_URL, json=payload, headers=self.headers, timeout=20)
        return self._parse_stream_response(resp.text)

    def claim_monthly_badge(self, month: int, year: int) -> dict[str, Any]:
        """
        Attempts to claim a monthly badge for a specific month and year (e.g. month=2, year=2025).
        Format sent to API: 'MM-YYYY' (e.g. '02-2025').
        """
        if not 1 <= month <= 12:
            raise ValueError("month must be between 1 and 12")
        if year < 1:
            raise ValueError("year must be a positive integer")

        amount = f"{month:02d}-{year}"
        return self._post_request("badge", amount)

    def claim_super(self) -> dict[str, Any]:
        """Requests Super Duolingo activation."""
        return self._post_request("super", 1)

    def claim_double_xp_boost(self) -> dict[str, Any]:
        """Requests 15-minute Double XP Boost."""
        return self._post_request("double_xp_boost", 1)

    def request_xp(self, amount: int = 500) -> dict[str, Any]:
        """Requests batch XP via Pro API."""
        return self._post_request("xp", amount)
