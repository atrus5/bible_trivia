# Bible Trivia

A real-time Bible trivia game built to run inside **ProPresenter** (web embed), with player phones, an admin dashboard, and daily/monthly leaderboards.

## Included Files
- `app.py`: Flask-SocketIO backend — SQLite persistence, auto-play cycling, monthly question tracking, reveal-answer flow, admin events.
- `data/questions_easy.json`: 40 easy questions.
- `data/questions_medium.json`: 30 medium questions.
- `data/questions_hard.json`: 30 hard questions.
- `templates/index.html`: Player interface (phones).
- `templates/display.html`: Stage display for ProPresenter.
- `templates/admin.html`: Admin dashboard (host control).
- `templates/leaderboard.html`: Public leaderboard page.
- `static/style.css`: Shared purple & gold theme.
- `requirements.txt`: Python dependencies.
- `validate.py`: Dev tool — checks all questions have 4 options, a valid answer, no duplicates.

Run `python validate.py` after editing the JSON question banks.

## How to Run
1. Install dependencies:
   `pip install -r requirements.txt`
2. Launch server:
   `python app.py`
3. Open the pages:
   - Players: `http://<your-ip>:5000/`
   - Stage display: `http://<your-ip>:5000/display`
   - **Admin dashboard: `http://<your-ip>:5000/admin`**
   - Leaderboard: `http://<your-ip>:5000/leaderboard`

## ProPresenter Setup
1. Add a Web View slide with URL `http://<your-ip>:5000/display`.
2. Toggle **Auto-play ON** in the admin dashboard.
3. Run the service like normal: when the trivia slide is shown, a question with a 30-second timer is on screen; the reveal happens automatically and the next question loads on its own.
4. When you cut to announcements and come back, ProPresenter may reload the web view — **nothing is lost**. The display re-syncs instantly to whatever is live (question, reveal, or countdown). Players' phones stay connected the whole time.
5. `http://<your-ip>:5000/display` can be loaded any time; it never resets the game.

## Auto-Play Flow
```
Question shown → 30s timer → answer locked → correct answer revealed
    → 8s pause (shows "Next question in Ns…") → next question → repeat
```
- Timer: 15/30/45/60s (admin selectable)
- Reveal pause: 5/10/15/20s (admin selectable)
- Turn auto-play OFF to drive each question manually with the buttons instead

## Admin Dashboard
Open `/admin` and enter the PIN (default **5364**, set `TRIVIA_ADMIN_PIN` to change it). From there you can:
- ▶️ Force the next question immediately
- 👁️ **Reveal the answer** — the correct option lights up green on every screen, with the verse reference
- 🤖 Toggle auto-play and set the reveal pause
- 🎲 Pick difficulty: Mixed / Easy / Medium / Hard (each tier is picked randomly)
- ⏱️ Set the timer: 15 / 30 / 45 / 60 seconds
- 📊 See question-pool usage for the month
- ⏹️ End the game (scores and used questions are kept)
- 👑 Crown the **monthly champion** (broadcast to all screens)

### Environment variables (optional)
- `TRIVIA_ADMIN_PIN` — change the admin PIN (default `5364`)
- `TRIVIA_SECRET` — Socket.IO secret key
- `DATABASE_URL` — Postgres connection string (e.g. Neon). When set, scores/settings/winner are stored in Postgres instead of local SQLite.

## Deploy to Render.com (free)
The repo includes `render.yaml` (Render Blueprint).

1. **Create a free Neon Postgres database** at [neon.tech](https://neon.tech) and copy the connection string
   (looks like `postgresql://neondb_owner:PASSWORD@ep-xxx.aws.neon.tech/neondb?sslmode=require`).
   This keeps scores, settings, and the monthly winner permanent even on Render's free plan.
2. Push this project to GitHub, then in Render: **New + → Blueprint** and select the repo —
   or create a **Web Service** manually with:
   - Root directory: *(leave blank — the app is at the repo root)*
   - Build command: `pip install -r requirements.txt`
   - Start command: `python app.py`
3. In the service's **Environment** tab add:
   - `DATABASE_URL` = your Neon connection string
   - `TRIVIA_ADMIN_PIN` = your PIN
4. Deploy. Your URLs become:
   - Players: `https://<service>.onrender.com/`
   - Stage display (ProPresenter web view): `https://<service>.onrender.com/display`
   - Admin: `https://<service>.onrender.com/admin`
   - Leaderboard: `https://<service>.onrender.com/leaderboard`

Notes:
- Free Render services sleep after ~15 min idle; the first request wakes them (~30s). With Neon the scores survive.
- Use the **pooled** connection string from Neon if you hit connection limits.
- ProPresenter just needs the `https://.../display` URL — the display re-syncs itself whenever the slide reloads.

## Scoring
- Base **10 points** + a speed bonus equal to seconds remaining
- Multiplied by difficulty: easy ×1, medium ×2, hard ×3
- One answer per player per question

## Question Rules
- Questions are picked **randomly**, per difficulty tier
- **No question repeats within a calendar month** (tracked in the DB; survives restarts)
- If a tier runs out mid-month (e.g., all 30 hard questions used), the picker falls back to the other tiers; the month's usage clears on the 1st

## Persistence (survives restarts)
- All answers, scores, daily/monthly boards, and the monthly winner
- Admin settings: difficulty, timer length, auto-play, reveal pause
- The live question and who already answered it — a mid-question restart resumes the same question

## Leaderboards
- **Daily** board resets every day; **monthly** board resets on the 1st
- The crowned monthly champion stays on the leaderboard page banner
