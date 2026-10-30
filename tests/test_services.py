import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.services import DuolingoDirectClient

class TestDuolingoDirectServices(unittest.TestCase):
    def setUp(self):
        self.client = DuolingoDirectClient(jwt_token="dummy.token.payload")

    def test_join_classroom_first_attempt_success(self):
        with patch.object(self.client, "_request") as mock_req:
            mock_req.return_value = (200, {"joined": True, "classroomId": "ABCDEF"})
            res = self.client.join_classroom("12345", "ABCDEF")

            self.assertTrue(res["success"])
            self.assertEqual(res["status_code"], 200)
            self.assertEqual(res["data"]["classroomId"], "ABCDEF")
            mock_req.assert_called_once_with(
                "POST",
                "https://schools-api.duolingo.com/classrooms/ABCDEF/join",
                json_data={"userId": "12345"}
            )

    def test_join_classroom_fallback_success(self):
        with patch.object(self.client, "_request") as mock_req:
            # First fails 404, second succeeds 200
            mock_req.side_effect = [
                (404, {"error": "not found"}),
                (200, {"success": True})
            ]
            res = self.client.join_classroom("12345", "XYZ123 ")

            self.assertTrue(res["success"])
            self.assertEqual(res["status_code"], 200)
            self.assertEqual(mock_req.call_count, 2)
            # Verify second attempt called
            second_call = mock_req.call_args_list[1]
            self.assertEqual(second_call[0][0], "POST")
            self.assertIn("XYZ123/join", second_call[0][1])

    def test_join_classroom_all_fail(self):
        with patch.object(self.client, "_request") as mock_req:
            mock_req.side_effect = [
                (404, {"error": "not found"}),
                (400, {"error": "invalid"}),
                (500, {"error": "server error"})
            ]
            res = self.client.join_classroom("12345", "FAILED")

            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 500)
            self.assertEqual(mock_req.call_count, 3)

    def test_join_classroom_exception_handling(self):
        with patch.object(self.client, "_request", side_effect=Exception("Network error")):
            res = self.client.join_classroom("12345", "ERRCOD")

            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 0)
            self.assertIn("Network error", res["data"]["error"])

    def test_get_quests_info_parsing(self):
        mock_goals_data = {
            "dailyGoals": [
                {"title": "Score 90% or higher", "progress": 2, "target": 2, "completed": True},
                {"type": "Earn 50 XP", "progress": 30, "goal": 50}
            ],
            "monthlyChallenge": {
                "month": 10,
                "year": 2026,
                "progress": 30,
                "target": 30,
                "earned": True
            },
            "friendsQuest": {
                "title": "Complete 75 lessons together",
                "progress": 45,
                "target": 75,
                "completed": False,
                "partner": "Budi"
            }
        }
        with patch.object(self.client, "get_goals_schema", return_value={}):
            with patch.object(self.client, "get_goals_progress", return_value=mock_goals_data):
                res = self.client.get_quests_info("12345")

                # Daily quests check
                self.assertEqual(len(res["daily_quests"]), 2)
                self.assertEqual(res["daily_quests"][0]["title"], "Score 90% or higher")
                self.assertTrue(res["daily_quests"][0]["completed"])
                self.assertEqual(res["daily_quests"][1]["title"], "Earn 50 XP")
                self.assertFalse(res["daily_quests"][1]["completed"])

                # Monthly challenge check
                self.assertEqual(res["monthly_challenge"]["month"], 10)
                self.assertEqual(res["monthly_challenge"]["year"], 2026)
                self.assertTrue(res["monthly_challenge"]["earned"])

                # Friends quest check
                self.assertIsNotNone(res["friends_quest"])
                self.assertEqual(res["friends_quest"]["partner"], "Budi")
                self.assertFalse(res["friends_quest"]["completed"])

    def test_get_quests_info_empty(self):
        with patch.object(self.client, "get_goals_schema", return_value={}):
            with patch.object(self.client, "get_goals_progress", return_value={}):
                res = self.client.get_quests_info("12345")
                self.assertEqual(res["daily_quests"], [])
                self.assertEqual(res["monthly_challenge"], {})
                self.assertIsNone(res["friends_quest"])

    def test_get_missing_monthly_badges(self):
        mock_goals = {
            "badges": {
                "earned": ["2025_01_monthly_challenge", "2025_02_monthly_goal"]
            },
            "monthlyChallenge": {
                "month": 10,
                "year": 2026,
                "earned": True
            }
        }
        with patch.object(self.client, "get_goals_schema", return_value={}):
            with patch.object(self.client, "get_goals_progress", return_value=mock_goals):
                missing = self.client.get_missing_monthly_badges("12345")
                self.assertIsInstance(missing, list)
                # Oct 2026 is earned, so (10, 2026) must not be in missing
                self.assertNotIn((10, 2026), missing)
                # Jan 2025 is earned, so (1, 2025) must not be in missing
                self.assertNotIn((1, 2025), missing)
                # Mar 2025 is not earned, so (3, 2025) must be in missing
                self.assertIn((3, 2025), missing)

    def test_complete_daily_quests_and_badges(self):
        mock_schema = {
            "goals": [
                {"category": "DAILY", "metric": "LESSONS", "badgeId": "b1"},
                {"category": "DAILY", "metric": "SPEND_TIME", "badgeId": "b2"},
                {"category": "MONTHLY", "metric": "QUESTS", "badgeId": "b_monthly"}
            ]
        }
        mock_progress = {
            "badges": {"earned": ["b1"]}
        }
        with patch.object(self.client, "get_goals_schema", return_value=mock_schema):
            with patch.object(self.client, "get_goals_progress", return_value=mock_progress):
                with patch.object(self.client, "update_goals_progress_batch") as mock_batch:
                    mock_batch.return_value = {"success": True, "status_code": 200, "data": {}}
                    res = self.client.complete_daily_quests_and_badges("12345")

                    self.assertTrue(res["success"])
                    mock_batch.assert_called_once()
                    updates = mock_batch.call_args[0][1]
                    # b1 was already earned, so only SPEND_TIME + QUESTS:50 should be submitted
                    metrics = [u["metric"] for u in updates]
                    self.assertIn("SPEND_TIME", metrics)
                    self.assertIn("QUESTS", metrics)
                    # Check QUESTS quantity is 50
                    quests_update = next(u for u in updates if u["metric"] == "QUESTS")
                    self.assertEqual(quests_update["quantity"], 50)

if __name__ == "__main__":
    unittest.main()
