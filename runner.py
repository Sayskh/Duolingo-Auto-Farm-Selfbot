import argparse
import math
import os
import random
import sys
import time

from core.auth import check_token_validity, get_user_id_from_jwt
from core.notifications import send_discord_webhook
from core.pro_services import DuolingoProClient
from core.services import DuolingoDirectClient
from dotenv import load_dotenv

load_dotenv()


def log(tag: str, message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {tag:<11} {message}")

def main():
    parser = argparse.ArgumentParser(
        description="Run selected Duolingo account actions through unofficial APIs."
    )
    parser.add_argument(
        "--jwt", default=os.getenv("JWT"), help="Duolingo JWT token"
    )
    parser.add_argument(
        "--webhook-url", default=os.getenv("WEBHOOK_URL"),
        help="Discord Webhook URL for reports and alerts"
    )
    parser.add_argument(
        "--sessions", type=int, default=int(os.getenv("XP_SESSIONS", "5")),
        help="Number of practice sessions to complete (default: 5)"
    )
    parser.add_argument(
        "--buy-freeze", action="store_true",
        default=os.getenv("AUTO_FREEZE", "true").lower() == "true",
        help="Buy a streak freeze when inventory is not full (enabled by default)"
    )
    parser.add_argument(
        "--claim-rewards", action="store_true",
        default=os.getenv("AUTO_CLAIM_REWARDS", "true").lower() == "true",
        help="Claim unclaimed reward bundles (enabled by default)"
    )
    parser.add_argument(
        "--claim-badges", action="store_true",
        default=os.getenv("AUTO_CLAIM_BADGES", "true").lower() == "true",
        help="Check and request a missing monthly badge (enabled by default)"
    )
    parser.add_argument(
        "--super", action="store_true",
        default=os.getenv("AUTO_SUPER", "false").lower() == "true",
        help="Request Super Duolingo activation through the third-party API"
    )
    parser.add_argument(
        "--classroom-code", default=os.getenv("CLASSROOM_CODE"),
        help="Duolingo for Schools classroom code (6 chars) to activate Super Duolingo natively"
    )
    parser.add_argument(
        "--leaderboard-top", action="store_true",
        default=os.getenv("AUTO_LEADERBOARD_TOP", "false").lower() == "true",
        help="Farm just enough XP to stay #1 on the weekly leaderboard"
    )

    args = parser.parse_args()

    if not args.jwt:
        parser.error("No JWT provided. Set JWT in .env or pass --jwt.")
    if args.sessions < 0:
        parser.error("--sessions must be zero or greater")

    print("Duolingo account automation")
    print("=" * 32)


    is_valid, _ = check_token_validity(args.jwt)
    if not is_valid:
        log("AUTH", "The JWT is invalid or expired.")
        if args.webhook_url:
            send_discord_webhook(
                webhook_url=args.webhook_url,
                title="Authentication Failed",
                description="JWT expired or invalid. Update JWT in settings.",
                color=0xEA2B2B,
            )
        sys.exit(1)
    log("AUTH", "JWT is valid.")

    user_id = get_user_id_from_jwt(args.jwt)
    timezone = os.getenv("TIMEZONE", "Asia/Jakarta")

    direct_client = DuolingoDirectClient(args.jwt)
    pro_client = DuolingoProClient(args.jwt)

    if args.classroom_code:
        try:
            log("SUPER", f"Attempting to join classroom {args.classroom_code} for native Super...")
            join_res = direct_client.join_classroom(user_id, args.classroom_code)
            if join_res.get("success"):
                log("SUPER", f"Successfully joined classroom {args.classroom_code} (HTTP {join_res.get('status_code')}).")
            else:
                log("SUPER", f"Failed to join classroom {args.classroom_code} (HTTP {join_res.get('status_code')}): {join_res.get('data')}")
        except Exception as e:
            log("SUPER", f"Classroom join error: {e}")

    profile = {}
    current_streak = None
    username = "Unknown"
    is_super = False
    log("PROFILE", "Fetching profile from Duolingo...")
    try:
        profile = direct_client.get_user_profile(user_id)
        username = profile.get("username", "Unknown")
        current_streak = profile.get("streak", 0)
        total_xp = profile.get("totalXp", 0)
        gems = profile.get("gems", 0)
        hearts = profile.get("hearts", 5)
        from_lang = profile.get("fromLanguage", "en")
        learn_lang = profile.get("learningLanguage", "es")
        is_super = bool(profile.get("hasPlus") or profile.get("hasSuper", False))

        super_str = " (Super Active)" if is_super else ""
        log("PROFILE", f"{username}{super_str} | {current_streak}-day streak | {total_xp:,} XP | {gems:,} gems | {hearts} hearts")
        log("PROFILE", f"Course: {learn_lang.upper()} from {from_lang.upper()}")
    except Exception:
        log("WARNING", "Could not fetch the profile. Using fallback course languages.")
        username = "Unknown"
        from_lang = "en"
        learn_lang = "es"
        gems = 0

    quests_summary = "Not checked"
    try:
        q_info = direct_client.get_quests_info(user_id, timezone=timezone)
        d_quests = q_info.get("daily_quests", [])
        completed_count = sum(1 for q in d_quests if q.get("completed"))
        total_count = len(d_quests)

        m_challenge = q_info.get("monthly_challenge") or {}
        monthly_prog = m_challenge.get("progress", 0)
        monthly_goal = m_challenge.get("goal", 30)

        quests_summary = f"{completed_count}/{total_count} complete"
        log("QUESTS", f"Daily Quests: {completed_count}/{total_count} complete | Monthly: {monthly_prog}/{monthly_goal}")
    except Exception as e:
        log("QUESTS", f"Failed to retrieve quests info: {e}")

    leaderboard_rank = None
    if args.leaderboard_top:
        sessions_explicit = any(arg == "--sessions" or arg.startswith("--sessions=") for arg in sys.argv)
        should_override = not sessions_explicit and args.sessions == 5
        try:
            log("LEADERBOARD", "Checking weekly leaderboard standings...")
            lb = direct_client.get_leaderboard(user_id)
            leaderboard_rank = lb.get("rank")
            my_score = lb.get("my_score", 0)
            top_score = lb.get("top_score", 0)
            second_score = lb.get("second_score", 0)
            log("LEADERBOARD", f"Rank #{leaderboard_rank} ({my_score:,} XP) | Top: {top_score:,} XP | #2: {second_score:,} XP")

            if should_override:
                target_xp = DuolingoDirectClient.calculate_target_xp(
                    my_score, top_score, second_score, leaderboard_rank
                )
                args.sessions = math.ceil(target_xp / 15) if target_xp > 0 else 0
                log("LEADERBOARD", f"Target: +{target_xp} XP -> running {args.sessions} sessions.")
            else:
                log("LEADERBOARD", f"Session count ({args.sessions}) explicitly set; keeping without override.")
        except Exception as e:
            log("WARNING", f"Leaderboard unavailable ({e}). Using default session count.")

    total_xp_gained = 0
    if args.sessions > 0:
        log("PRACTICE", f"Starting {args.sessions} practice sessions...")

        for i in range(1, args.sessions + 1):
            try:
                log("PRACTICE", f"[{i}/{args.sessions}] Starting session...")
                session_data = direct_client.start_practice_session(from_lang, learn_lang)
                session_id = session_data.get("id")

                simulated_duration = random.randint(35, 60)
                wait_time = random.uniform(3.0, 5.0)
                time.sleep(wait_time)

                completed = direct_client.complete_practice_session(
                    session_data, duration_seconds=simulated_duration
                )
                xp_gained = completed.get("xpGain", 15)
                total_xp_gained += xp_gained
                log("PRACTICE", f"[{i}/{args.sessions}] Completed. Earned {xp_gained} XP (session {session_id}).")

                if i < args.sessions:
                    time.sleep(random.uniform(2.0, 3.5))

            except Exception as e:
                log("PRACTICE", f"[{i}/{args.sessions}] Session failed: {e}")

        log("PRACTICE", f"Total XP earned: {total_xp_gained:,}.")
    else:
        log("PRACTICE", "Skipped because the session count is 0.")


    claimed_gems = 0
    claimed_count = 0
    if args.claim_rewards:
        try:
            log("REWARDS", "Checking for unclaimed rewards...")
            claim_res = direct_client.claim_unconsumed_rewards(user_id, max_claims=35)
            claimed_count = claim_res.get("claimed_count", 0)
            claimed_gems = claim_res.get("claimed_gems", 0)

            if claimed_count > 0:
                log("REWARDS", f"Claimed {claimed_count} rewards and {claimed_gems:,} gems.")
                for item in claim_res.get("details", [])[:5]:
                    log("REWARDS", f"- {item['type']}: {item['gems']:,} gems")
                if len(claim_res.get("details", [])) > 5:
                    log("REWARDS", f"- And {len(claim_res['details']) - 5} more rewards.")
            else:
                log("REWARDS", "No unclaimed rewards found.")
        except Exception as e:
            log("REWARDS", f"Could not check rewards: {e}")

    badge_status = "Not checked"
    if args.claim_badges:
        try:
            log("BADGES", "Checking monthly badge progress...")
            missing_badges = direct_client.get_missing_monthly_badges(user_id)
            if missing_badges:
                log("BADGES", f"Found {len(missing_badges)} missing monthly badges:")
                for m, y in missing_badges[:4]:
                    log("BADGES", f"- {m:02d}-{y}")
                if len(missing_badges) > 4:
                    log("BADGES", f"- And {len(missing_badges) - 4} more.")


                target_month, target_year = missing_badges[0]
                log("BADGES", f"Requesting badge {target_month:02d}-{target_year}...")
                badge_resp = pro_client.claim_monthly_badge(target_month, target_year)

                status = badge_resp.get("status")
                notification = badge_resp.get("notification", {})
                notif_head = notification.get("head", "")
                notif_body = notification.get("body", "")

                if status == "success" or badge_resp.get("percentage", 0) > 0:
                    badge_status = f"Request succeeded ({target_month:02d}-{target_year})"
                    log("BADGES", badge_status)
                elif "Limit Warning" in notif_head or "resets back" in notif_body:
                    badge_status = f"Cooldown: {notif_body}"
                    log("BADGES", badge_status)
                    log("BADGES", "The next scheduled workflow may retry this request.")
                else:
                    badge_status = f"Response: {badge_resp.get('raw', badge_resp)}"
                    log("BADGES", badge_status)
            else:
                badge_status = "No missing monthly badges found."
                log("BADGES", badge_status)
        except Exception as e:
            badge_status = f"Failed: {e}"
            log("BADGES", badge_status)


    if args.super:
        try:
            log("SUPER", "Requesting Super activation...")
            super_res = pro_client.claim_super()
            log("SUPER", f"Response: {super_res.get('status', 'unknown')}")
        except Exception as e:
            log("SUPER", f"Activation request failed: {e}")

    log("MAINTENANCE", "Practice sessions may refill hearts, depending on account settings.")
    if args.buy_freeze:
        try:
            log("MAINTENANCE", "Checking streak freeze inventory...")
            res = direct_client.buy_streak_freeze(user_id)
            code = res.get("status_code")
            if code in (200, 201):
                log("MAINTENANCE", "Streak freeze purchased or replenished.")
            elif code == 400:
                log("MAINTENANCE", "Streak freeze inventory is full (2/2).")
            else:
                log("MAINTENANCE", f"Streak freeze request returned HTTP {code}.")
        except Exception as e:
            log("MAINTENANCE", f"Could not check streak freeze: {e}")

    print("\nRun summary")
    print("=" * 32)
    print(f"Practice XP : {total_xp_gained:,}")
    print(f"Rewards     : {claimed_count}")
    print(f"Gems        : {claimed_gems:,}")
    print(f"Badges      : {badge_status}")
    print(f"Daily Quests: {quests_summary}")
    streak_summary = current_streak if current_streak is not None else "Not available"
    print(f"Streak      : {streak_summary}")
    lb_summary = f"#{leaderboard_rank}" if leaderboard_rank is not None else "Not checked"
    print(f"Leaderboard : {lb_summary}")
    if is_super or args.classroom_code:
        print(f"Super       : {'Active' if is_super else 'Requested'}")

    if args.webhook_url:
        streak_display = f"{streak_summary} days" if current_streak is not None else str(streak_summary)
        fields = [
            {"name": "Learner", "value": username, "inline": True},
            {"name": "Practice XP", "value": f"+{total_xp_gained:,} XP", "inline": True},
            {"name": "Streak", "value": streak_display, "inline": True},
            {"name": "Leaderboard", "value": lb_summary, "inline": True},
            {"name": "Gems", "value": f"{gems:,} (+{claimed_gems:,})", "inline": True},
            {"name": "Daily Quests", "value": quests_summary, "inline": True},
        ]
        if is_super or args.classroom_code:
            fields.append({"name": "Super", "value": "Active" if is_super else "Requested", "inline": True})
        fields.append({"name": "Badges", "value": badge_status, "inline": False})
        send_discord_webhook(
            webhook_url=args.webhook_url,
            title="Duolingo Run Summary",
            description="",
            color=0x58CC02,
            fields=fields,
        )

if __name__ == "__main__":
    main()
