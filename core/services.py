import datetime
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
    LEADERBOARD_URL = "https://duolingo-leaderboards-prod.duolingo.com/leaderboards/7d9f5dd1-8423-491a-91f2-2532052038ce"

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
        fields = "id,username,currentCourse,fromLanguage,learningLanguage,hearts,totalXp,streak,streakData,gems,lingots,rewardBundles,hasPlus"
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

    def get_goals_schema(self) -> dict[str, Any]:
        """
        Fetches official goals schema definitions from goals-api.duolingo.com/schema.
        """
        url = "https://goals-api.duolingo.com/schema?ui_language=en"
        status, data = self._request("GET", url)
        if status != 200:
            logger.warning(f"Could not fetch goals schema (HTTP {status})")
            return {}
        return data

    def update_goals_progress_batch(
        self,
        user_id: str,
        metric_updates: list[dict[str, Any]],
        timezone: str = "Asia/Jakarta"
    ) -> dict[str, Any]:
        """
        Submits batch progress updates to https://goals-api.duolingo.com/users/{user_id}/progress/batch.
        """
        # ponytail: direct batch progress update; add individual quest listener if event streaming is added
        url = f"https://goals-api.duolingo.com/users/{quote(str(user_id), safe='')}/progress/batch"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = {
            "metric_updates": metric_updates,
            "timezone": timezone,
            "timestamp": now_iso
        }
        status, data = self._request("POST", url, json_data=payload)
        return {"status_code": status, "success": status in (200, 201), "data": data}

    def complete_daily_quests_and_badges(
        self,
        user_id: str,
        timezone: str = "Asia/Jakarta"
    ) -> dict[str, Any]:
        """
        Completes daily quests and advances monthly challenge progress natively
        via goals-api.duolingo.com/users/{user_id}/progress/batch.
        """
        schema = self.get_goals_schema()
        progress = self.get_goals_progress(user_id, timezone=timezone)
        earned = set(progress.get("badges", {}).get("earned", []))

        metrics = set()
        goals = schema.get("goals", []) if isinstance(schema, dict) else []
        for goal in goals:
            if not isinstance(goal, dict):
                continue
            cat = (goal.get("category") or "").upper()
            is_daily = "DAILY" in cat
            done = (goal.get("badgeId") in earned) or (goal.get("goalId") in earned)
            if is_daily and not done and goal.get("metric"):
                metrics.add(goal["metric"])

        if not metrics:
            metrics = {
                "LESSONS", "SPEND_TIME", "PERFECT_LESSONS",
                "LISTEN_EXERCISES", "SPEAK_EXERCISES", "CORRECT_IN_A_ROW"
            }

        updates = [{"metric": m, "quantity": 2000} for m in sorted(metrics)]
        # Add 50 completed quests to satisfy monthly challenge badge
        updates.append({"metric": "QUESTS", "quantity": 50})

        res = self.update_goals_progress_batch(user_id, updates, timezone=timezone)
        return res

    def join_classroom(self, user_id: str, classroom_code: str) -> dict[str, Any]:
        """
        Attempts to join a Duolingo classroom using a 6-character classroom code.
        Permanent Super Duolingo activation via Schools.
        """
        # ponytail: join existing classroom code for permanent Super; add auto-create classroom teacher flow if manual code generation becomes burdensome
        code = classroom_code.strip()
        attempts = [
            ("POST", f"https://schools-api.duolingo.com/classrooms/{code}/join", {"userId": user_id}),
            ("POST", f"{self.BASE_URL}/classrooms/{code}/join", {"userId": user_id}),
            ("POST", f"{self.BASE_URL}/users/{user_id}/classrooms", {"classroomId": code}),
        ]

        last_res = {"success": False, "status_code": 0, "data": {}}
        for method, url, payload in attempts:
            try:
                status, data = self._request(method, url, json_data=payload)
                if status in (200, 201):
                    return {"success": True, "status_code": status, "data": data}
                last_res = {"success": False, "status_code": status, "data": data}
            except Exception as e:
                last_res = {"success": False, "status_code": 0, "data": {"error": str(e)}}

        return last_res

    def get_quests_info(self, user_id: str, timezone: str = "Asia/Jakarta") -> dict[str, Any]:
        """
        Fetches official goals and provides parsed summary for daily, monthly, and friends quests.
        """
        goals_data = self.get_goals_progress(user_id, timezone=timezone)
        if not isinstance(goals_data, dict):
            goals_data = {}
        earned = set(goals_data.get("badges", {}).get("earned", []))

        schema = self.get_goals_schema()
        schema_goals = schema.get("goals", []) if isinstance(schema, dict) else []

        daily_quests = []
        monthly_challenge = {}

        if schema_goals:
            for g in schema_goals:
                if not isinstance(g, dict):
                    continue
                cat = (g.get("category") or "").upper()
                badge_id = g.get("badgeId")
                goal_id = g.get("goalId")
                is_done = (badge_id in earned) or (goal_id in earned)

                if "DAILY" in cat:
                    title = g.get("title") or g.get("name") or g.get("metric", "Daily Quest")
                    target = g.get("target") or g.get("goal", 1)
                    prog = target if is_done else g.get("progress", 0)
                    daily_quests.append({
                        "title": title,
                        "progress": prog,
                        "goal": target,
                        "completed": is_done
                    })
                elif "MONTHLY" in cat and not monthly_challenge:
                    target = g.get("target") or g.get("goal", 30)
                    now = datetime.datetime.now()
                    prog = target if is_done else 0
                    monthly_challenge = {
                        "month": now.month,
                        "year": now.year,
                        "progress": prog,
                        "goal": target,
                        "earned": is_done
                    }

        # Fallback to direct goals_data if schema returned no daily quests
        if not daily_quests:
            raw_daily = (
                goals_data.get("dailyGoals")
                or goals_data.get("dailyQuests")
                or goals_data.get("goals", [])
            )
            if isinstance(raw_daily, list):
                for q in raw_daily:
                    if not isinstance(q, dict):
                        continue
                    title = q.get("title") or q.get("type", "Quest")
                    progress = q.get("progress", 0)
                    goal = q.get("target", q.get("goal", 1))
                    completed = bool(q.get("completed", progress >= goal if goal else False))
                    daily_quests.append({
                        "title": title,
                        "progress": progress,
                        "goal": goal,
                        "completed": completed
                    })

        if not monthly_challenge:
            monthly_raw = goals_data.get("monthlyChallenge") or goals_data.get("monthlyGoal")
            if isinstance(monthly_raw, dict):
                m_prog = monthly_raw.get("progress", 0)
                m_goal = monthly_raw.get("target", monthly_raw.get("goal", 30))
                monthly_challenge = {
                    "month": monthly_raw.get("month"),
                    "year": monthly_raw.get("year"),
                    "progress": m_prog,
                    "goal": m_goal,
                    "earned": bool(monthly_raw.get("earned", monthly_raw.get("completed", m_prog >= m_goal if m_goal else False)))
                }

        friends_raw = goals_data.get("friendsQuest") or goals_data.get("partnerGoal")
        friends_quest = None
        if isinstance(friends_raw, dict):
            f_prog = friends_raw.get("progress", 0)
            f_goal = friends_raw.get("target", friends_raw.get("goal", 1))
            friends_quest = {
                "title": friends_raw.get("title", "Friends Quest"),
                "progress": f_prog,
                "goal": f_goal,
                "completed": bool(friends_raw.get("completed", f_prog >= f_goal if f_goal else False)),
                "partner": friends_raw.get("partner") or friends_raw.get("partnerName")
            }

        return {
            "daily_quests": daily_quests,
            "monthly_challenge": monthly_challenge,
            "friends_quest": friends_quest
        }

    def get_missing_monthly_badges(self, user_id: str, timezone: str = "Asia/Jakarta") -> list[tuple[int, int]]:
        """
        Identifies which monthly badges (current year back to 2024) are unearned.
        Returns a list of (month, year) tuples.
        """
        goals_data = self.get_goals_progress(user_id, timezone=timezone)
        earned = set(goals_data.get("badges", {}).get("earned", []))

        # Check current month quest earned status from schema or goals_data
        schema = self.get_goals_schema()
        schema_goals = schema.get("goals", []) if isinstance(schema, dict) else []
        current_earned = False
        for g in schema_goals:
            if isinstance(g, dict) and "MONTHLY" in (g.get("category") or "").upper():
                badge_id = g.get("badgeId")
                goal_id = g.get("goalId")
                if (badge_id in earned) or (goal_id in earned):
                    current_earned = True
                    break

        if not current_earned:
            monthly_raw = goals_data.get("monthlyChallenge") or goals_data.get("monthlyGoal")
            if isinstance(monthly_raw, dict):
                current_earned = bool(monthly_raw.get("earned", monthly_raw.get("completed", False)))

        now = datetime.datetime.now()
        current_m = now.month
        current_y = now.year

        missing = []
        # Duolingo monthly challenge badge system started in December 2021
        for year in range(2021, current_y + 1):
            start_m = 12 if year == 2021 else 1
            end_m = current_m if year == current_y else 12
            for month in range(start_m, end_m + 1):
                if year == current_y and month == current_m:
                    if not current_earned:
                        missing.append((month, year))
                    continue

                pref1 = f"{year}_{month:02d}"
                pref2 = f"{year}_{month}_"
                pref3 = f"{year}-{month:02d}"
                is_earned = any(
                    b.startswith(pref1) or b.startswith(pref2) or b.startswith(pref3)
                    for b in earned
                )
                if not is_earned:
                    missing.append((month, year))

        return missing

    def get_leaderboard(self, user_id: str) -> dict[str, Any]:
        """Fetches weekly leaderboard rankings and scores for the user's cohort."""
        now_ms = int(time.time() * 1000)
        url = f"{self.LEADERBOARD_URL}/users/{quote(str(user_id), safe='')}?client_unlocked=true&get_reactions=true&_={now_ms}"
        status, data = self._request("GET", url)
        if status != 200:
            raise RuntimeError(f"Failed to fetch leaderboard (HTTP {status}): {data}")

        rankings = []
        if isinstance(data, dict):
            active = data.get("active") or {}
            cohort = active.get("cohort") if isinstance(active, dict) else {}
            if isinstance(cohort, dict) and "rankings" in cohort:
                rankings = cohort["rankings"]
            elif isinstance(active, dict) and "rankings" in active:
                rankings = active["rankings"]
            elif "rankings" in data:
                rankings = data["rankings"]
            elif "users" in data:
                rankings = data["users"]

        parsed_entries = []
        for entry in rankings:
            if not isinstance(entry, dict):
                continue
            uid = str(entry.get("user_id") or entry.get("userId") or entry.get("id") or "")
            score = entry.get("score")
            if score is None:
                score = entry.get("totalXp", entry.get("xp", entry.get("points", 0)))
            try:
                score = int(score)
            except (ValueError, TypeError):
                score = 0
            parsed_entries.append((uid, score))

        parsed_entries.sort(key=lambda x: x[1], reverse=True)
        scores = [s for _, s in parsed_entries]

        my_score = 0
        rank = len(scores) + 1 if scores else 1
        for idx, (uid, s) in enumerate(parsed_entries):
            if uid == str(user_id):
                my_score = s
                rank = idx + 1
                break

        top_score = scores[0] if scores else my_score
        second_score = scores[1] if len(scores) > 1 else (my_score if rank == 1 else top_score)

        return {
            "my_score": my_score,
            "rank": rank,
            "top_score": top_score,
            "second_score": second_score,
            "scores": scores,
        }

    @staticmethod
    def calculate_target_xp(my_score: int, top_score: int, second_score: int, rank: int) -> int:
        """Calculates natural-looking XP needed to secure #1, capped at 300 XP per run."""
        if rank == 1:
            gap = my_score - second_score
            if gap > 100:
                return 0
            target = random.randint(15, 50)
        else:
            buffer = random.randint(15, 75)
            target = top_score - my_score + buffer

        # ponytail: cap at 300 XP/run; upgrade to dynamic velocity tracking if league competition ramps up
        return max(0, min(target, 300))

