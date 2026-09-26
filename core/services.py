import json
import logging
import random
import time
from typing import Any
from urllib.parse import quote

import requests

try:
    from scrapling.fetchers import FetcherSession
except ImportError:
    FetcherSession = None

logger = logging.getLogger("DuoDirect")
HAS_SCRAPLING = FetcherSession is not None

class DuolingoDirectClient:
    """Client for Duolingo's web API."""

    BASE_URL = "https://www.duolingo.com/2017-06-30"

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
        self._req_session = requests.Session()
        self._req_session.headers.update(self.headers)

    def _request(self, method: str, url: str, json_data: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        """Executes an HTTP request using Scrapling (if available) or requests.Session as fallback."""
        if self.use_scrapling and FetcherSession is not None and method.upper() in ("GET", "POST", "PUT"):
            try:
                with FetcherSession(impersonate="chrome", stealthy_headers=True) as session:
                    if method.upper() == "GET":
                        resp = session.get(url, headers=self.headers)
                    elif method.upper() == "POST":
                        resp = session.post(url, json=json_data, headers=self.headers)
                    else:
                        resp = session.put(url, json=json_data, headers=self.headers)

                    status_code = getattr(resp, "status", None)
                    if status_code is None:
                        status_code = getattr(resp, "status_code", 200)
                    if hasattr(resp, "body") and resp.body:
                        body_text = resp.body.decode("utf-8", errors="replace")
                    else:
                        body_text = getattr(resp, "text", "") or ""

                    try:
                        return status_code, json.loads(body_text) if body_text else {}
                    except json.JSONDecodeError:
                        return status_code, {"raw": body_text}
            except Exception as e:
                logger.warning(f"Scrapling request failed ({e}), falling back to requests.Session")

        # Standard requests (also handles PATCH)
        resp = self._req_session.request(method, url, json=json_data)
        try:
            return resp.status_code, resp.json()
        except json.JSONDecodeError:
            return resp.status_code, {"raw": resp.text}

    def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """Fetches user metadata including streak, hearts, gems, current language, and total XP."""
        fields = "id,username,currentCourse,fromLanguage,learningLanguage,hearts,totalXp,streak,streakData,gems,lingots,rewardBundles"
        url = f"{self.BASE_URL}/users/{user_id}?fields={fields}"
        status, data = self._request("GET", url)
        if status != 200:
            raise RuntimeError(f"Failed to fetch profile (HTTP {status}): {data}")
        return data

    def start_practice_session(self, from_language: str, learning_language: str) -> dict[str, Any]:
        """Initiates a practice lesson session on Duolingo servers."""
        url = f"{self.BASE_URL}/sessions"
        payload = {
            "challengeTypes": [
                "characterMatch", "characterPuzzle", "definition", "dialogue", "form",
                "freeResponse", "gapFill", "judge", "listen", "name", "listenComplete",
                "match", "readComprehension", "select", "selectPronunciation",
                "selectTranscription", "syllableTap", "syllableListenTap", "speak",
                "tapCloze", "tapClozeTable", "tapComplete", "tapCompleteTable",
                "translate", "typeCloze", "typeClozeTable", "typeCompleteTable",
                "writeComprehension"
            ],
            "fromLanguage": from_language,
            "isFinalLevel": False,
            "isV2": True,
            "juicy": True,
            "learningLanguage": learning_language,
            "smartLearnerVariant": "DEFAULT",
            "type": "GLOBAL_PRACTICE"
        }
        status, data = self._request("POST", url, json_data=payload)
        if status not in (200, 201):
            raise RuntimeError(f"Failed to start practice session (HTTP {status}): {data}")
        return data

    def complete_practice_session(self, session_data: dict[str, Any], duration_seconds: int = 45) -> dict[str, Any]:
        """Completes the initiated session, claiming XP and maintaining daily streak."""
        session_id = session_data.get("id")
        if not session_id:
            raise ValueError(f"session_data missing 'id': {session_data}")

        url = f"{self.BASE_URL}/sessions/{session_id}"
        now = int(time.time())
        start_time = now - duration_seconds

        payload = dict(session_data)
        payload.update({
            "heartsLeft": 5,
            "startTime": start_time,
            "endTime": now,
            "failed": False,
            "maxInLessonStreak": random.randint(12, 18),
            "shouldLearnThings": True,
            "enableBonusPoints": True
        })

        status, data = self._request("PUT", url, json_data=payload)
        if status != 200:
            raise RuntimeError(f"Failed to complete session (HTTP {status}): {data}")
        return data

    def buy_streak_freeze(self, user_id: str) -> dict[str, Any]:
        """Purchases a streak freeze item from the shop if inventory is not full."""
        url = f"{self.BASE_URL}/users/{user_id}/shop-items"
        payload = {"itemId": "streak_freeze"}
        status, data = self._request("POST", url, json_data=payload)
        return {"status_code": status, "data": data}

    def claim_unconsumed_rewards(self, user_id: str, max_claims: int = 30) -> dict[str, Any]:
        """
        Scans for unclaimed reward bundles (Monthly Challenges, Quests, Tournament, Chests, Gems)
        and claims them directly via PATCH /users/{user_id}/rewards/{reward_id}.
        """
        profile = self.get_user_profile(user_id)
        bundles = profile.get("rewardBundles", [])

        claimed_count = 0
        claimed_gems = 0
        details = []

        for b in bundles:
            b_type = b.get("rewardBundleType", "UNKNOWN")
            for r in b.get("rewards", []):
                if not r.get("consumed"):
                    reward_id = r.get("id")
                    url = f"{self.BASE_URL}/users/{user_id}/rewards/{reward_id}"
                    status, _ = self._request("PATCH", url, json_data={"consumed": True})

                    if status == 200:
                        claimed_count += 1
                        amt = r.get("amount") or 0
                        if r.get("items"):
                            for item in r.get("items", []):
                                if item.get("itemType") == "GEM":
                                    amt += (item.get("amount") or 0)
                        claimed_gems += amt
                        details.append({
                            "type": b_type,
                            "reward_id": reward_id,
                            "gems": amt
                        })

                        if claimed_count >= max_claims:
                            return {
                                "claimed_count": claimed_count,
                                "claimed_gems": claimed_gems,
                                "details": details,
                                "remaining": True
                            }

        return {
            "claimed_count": claimed_count,
            "claimed_gems": claimed_gems,
            "details": details,
            "remaining": False
        }

    def get_goals_progress(self, user_id: str, timezone: str = "Asia/Jakarta") -> dict[str, Any]:
        """
        Fetches official goals and badge progress from goals-api.duolingo.com.
        """
        url = f"https://goals-api.duolingo.com/users/{quote(str(user_id), safe='')}/progress"
        status, data = self._request("GET", f"{url}?timezone={quote(timezone, safe='')}")
        if status != 200:
            logger.warning(f"Could not fetch goals progress (HTTP {status})")
            return {}
        return data

    def get_missing_monthly_badges(self, user_id: str, timezone: str = "Asia/Jakarta") -> list[tuple[int, int]]:
        """
        Identifies which monthly badges (2024 - 2025) are unearned.
        Returns a list of (month, year) tuples.
        """
        goals_data = self.get_goals_progress(user_id, timezone=timezone)
        earned = set(goals_data.get("badges", {}).get("earned", []))

        missing = []
        # Target 2025 (months 1-12) and 2024 (months 1-12)
        for year in [2025, 2024]:
            for month in range(1, 13):
                badge_key_1 = f"{year}_{month:02d}_monthly_challenge"
                badge_key_2 = f"{year}_{month:02d}_monthly_goal"
                if badge_key_1 not in earned and badge_key_2 not in earned:
                    missing.append((month, year))

        return missing
