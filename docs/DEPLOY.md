# Putting the assistant on the internet (optional)

You do **not** need this to run the project: `cp .env.example .env`, add your key, `python3 run.py`. This page is only for a public copy that other people can open.

**The one thing to understand first:** on a public copy, every visitor's question is paid for by the API key on the server. So use a **separate key** made just for this, set a **monthly spend limit** on it in the Anthropic Console (look for the spend-limit setting under the Console's billing / limits pages), and turn on the limits below. The limit in the Console is the real hard stop; the limits in this app are a second fence.

## Settings for a public copy (all optional; nothing is limited when they are not set)

| setting | what it does |
|---|---|
| `DAILY_BUDGET_USD=3` | all visitors together can spend this much per day (UTC); after that the site says so and starts again at midnight UTC. Kept in memory, so a restart starts the day again: keep the Console limit too |
| `RATE_LIMIT_PER_HOUR=20` | one visitor can ask this many questions per hour |
| `TRUST_PROXY=on` | the host puts one proxy in front of the site (Render, Fly.io, Railway do): count visitors by the address the proxy reports. Leave it off when nothing is in front, or a visitor could fake their address |
| `MAX_CONVERSATIONS=2` | conversations open at once. **Each one runs its own assistant process that takes about 260 MB of memory**, on top of about 80 MB for the site. A 512 MB host fits exactly one; use 2 or 3 on a plan with 1 GB or more |
| `SESSION_BUDGET_USD=0.75` | one conversation ends when it has spent this much |
| `MODEL=sonnet` | haiku is the smallest model; sonnet is what everything was tested on |
| `PORT` | hosting services set this by themselves; the app listens on it |

When the app is reachable from other machines and none of the first two are set, it prints a warning at start-up.

## Render, without Docker

Render runs Python straight from your GitHub repository. Push the repository first (the fork already is), then either use the file or type the settings in.

**With the file:** on render.com choose **New → Blueprint**, pick the repository, and Render reads `render.yaml`.

**By hand:** choose **New → Web Service**, pick the repository, and fill in:

| field | value |
|---|---|
| Runtime | Python |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m app.server --no-open` |
| Health check path | `/api/health` |
| Environment variables | `ANTHROPIC_API_KEY` (paste the separate key here, in Render's page), `APP_HOST=0.0.0.0`, and the settings from the table above |

Two things that are easy to miss:
* **`APP_HOST=0.0.0.0` is required.** Without it the app listens only on its own computer and Render cannot reach it. `PORT` is set by Render itself and the app uses it.
* The app needs **Python 3.10 or newer**. Render's default is new enough; if the build complains about the Python version, set `PYTHON_VERSION` to a full version number such as one starting `3.12.`.

The build downloads about 300 MB of packages and takes a few minutes. A free service goes to sleep when nobody uses it, so the first visit after a pause is slow, and it has 512 MB of memory, so keep `MAX_CONVERSATIONS=1` there.

When it is up, open the address Render shows and ask the three sample questions from the README, then put the address in the README (the note at the top has a blank for it).

## Other hosts

Anything that can run a long-lived Python process and set environment variables works the same way (same build command, start command and variables). **Vercel is probably the wrong fit** (I have not tried it): it is built for short serverless functions, and this app is a long-running server that streams answers and starts a helper process of about 260 MB for each visitor.

## Checking it works

* `GET /api/health` answers `{"ok": true, ...}` without using any credit.
* Ask one question in the page. If you see "The Anthropic account behind this key has no credits left", add credits in the Console.
* Ask more than `RATE_LIMIT_PER_HOUR` questions from one browser: the page shows "That is a lot of questions in an hour".
