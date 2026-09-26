# Duolingo Automation CLI

An unofficial Python CLI for selected Duolingo account actions. It uses Duolingo web endpoints and can optionally call a third-party service for badge and Super requests. This project is not affiliated with Duolingo.

> [!WARNING]
> Automated activity may violate Duolingo's terms or lead to account restrictions. Use only with an account you control. Review the code and understand each action before running it.

> [!CAUTION]
> The DuolingoPRO client sends your Duolingo JWT to `api.duolingopro.net`. This is a third-party service, not operated by Duolingo. Do not use those features unless you trust that service with your account credential.

## Features

- Start and complete practice sessions through Duolingo's web API.
- Check and claim unclaimed reward bundles.
- Check monthly badge progress and optionally send a badge request through DuolingoPRO.
- Optionally buy a streak freeze or request Super activation.
- Run locally or use the included scheduled/manual GitHub Actions workflow.

The endpoints are unofficial and can change without notice. Some requests can change account state or spend in-app currency.

## Local setup

### 1. Install Python dependencies

Use Python 3.10 or later. From the project directory, create a virtual environment:

```bash
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

### 2. Get your Duolingo JWT

Sign in to [duolingo.com](https://www.duolingo.com/) in a browser, then open Developer Tools with `F12`.

- Chrome or Edge: open **Application**, then **Cookies**, then `https://www.duolingo.com`.
- Firefox: open **Storage**, then **Cookies**, then `https://www.duolingo.com`.

Copy the value of the `jwt_token` cookie. Do not include the cookie name or quotes. A JWT grants access to your account, so treat it like a password. Never share it in an issue, screenshot, chat, commit, or workflow file. If it leaks, revoke the session where possible and replace the token.

The CLI gets your user ID from the JWT's `sub` claim. You do not need to configure an ID separately. To inspect it, use the browser's Network panel while signed in or decode the token payload locally. Do not paste the JWT into an online decoder.

### 3. Configure the project

Copy `.env.example` to `.env`:

PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS or Linux:

```bash
cp .env.example .env
```

Edit `.env` and set your token:

```dotenv
JWT=your_token_value

XP_SESSIONS=0
AUTO_FREEZE=false
AUTO_CLAIM_REWARDS=false
AUTO_CLAIM_BADGES=false
AUTO_SUPER=false
```

The goals and badge progress request uses `Asia/Jakarta` as its timezone. `.env` is ignored by Git. Keep your real token out of tracked files.

### 4. Run the CLI

See the available command-line options:

```bash
python runner.py --help
```

Start the runner with values from `.env`:

```bash
python runner.py
```

The default practice session count is five. Reward claims, badge checks, and streak-freeze checks also default to enabled unless you set their `AUTO_*` environment variables to `false`. Start cautiously by setting `XP_SESSIONS=0` and all `AUTO_*` values to `false`, then enable only actions you intend to use.

For example, this command skips practice sessions and requests reward claims:

```bash
python runner.py --sessions 0 --claim-rewards
```

The command-line switches are opt-in, but the corresponding `AUTO_*` environment variables can enable these actions by default. Review the account impact before enabling them.

## GitHub Actions setup

The workflow in `.github/workflows/auto.yml` runs every four hours and supports manual runs from the repository's **Actions** tab. Scheduled runs complete five practice sessions, claim rewards, check badges, and check streak-freeze inventory. In the workflow, `AUTO_FREEZE`, `AUTO_CLAIM_REWARDS`, and `AUTO_CLAIM_BADGES` are enabled. `AUTO_SUPER` stays disabled unless you enable it in a manual run. Read `auto.yml` before enabling the schedule.

To configure a repository:

1. Open **Settings > Secrets and variables > Actions**.
2. Add a repository secret named `JWT` with the value of your `jwt_token` cookie.
3. Review repository visibility and workflow permissions. Anyone who can change a workflow may be able to use configured secrets.
4. Enable Actions and start with a manual run using conservative inputs.

Do not put your JWT directly in a workflow file. GitHub masks configured secrets in logs, but you should still treat them as credentials. Scheduled workflows can perform account actions without another confirmation.

## Example output

Your output depends on your account and API responses. A run may look like this:

```text
Duolingo account automation
================================
[12:34:56] AUTH        JWT is valid.
[12:34:56] PROFILE     learner | 12-day streak | 4,250 XP | 320 gems | 5 hearts
[12:34:56] PROFILE     Course: ES from EN
[12:34:56] PRACTICE    Starting 1 practice sessions...
[12:34:57] PRACTICE    [1/1] Starting session...
[12:35:02] PRACTICE    [1/1] Completed. Earned 15 XP (session example-id).
[12:35:02] PRACTICE    Total XP earned: 15.
[12:35:02] MAINTENANCE Practice sessions may refill hearts, depending on account settings.

Run summary
================================
Practice XP : 15
Rewards     : 0
Gems        : 0
Badges      : Not checked
Streak      : 12
```

Names, profile values, timing, and API results above are illustrative, not guaranteed.

## Troubleshooting

- **No JWT found:** confirm `.env` is in the project directory and contains `JWT=...`, or pass `--jwt` to the CLI.
- **JWT rejected or expired:** sign in again, copy the current `jwt_token` cookie, and update `.env` or the GitHub Actions secret.
- **Profile or action request failed:** check network access and remember that the unofficial endpoints can change. Remove personal data before sharing logs.


## Project layout

```text
runner.py                       CLI entry point
core/auth.py                    JWT parsing and expiration checks
core/services.py                Duolingo web API client
core/pro_services.py            Third-party DuolingoPRO API client
.github/workflows/auto.yml      Scheduled and manual GitHub Actions workflow
.env.example                    Local configuration template
requirements.txt                Python dependencies
```

## Credits

[DuolingoPRO](https://www.duolingopro.net/) provides the third-party service used for badge and Super requests.
