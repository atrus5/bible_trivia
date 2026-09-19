# Bible Trivia

A real-time Bible trivia game built to run inside **ProPresenter** (web embed), with player phones, an admin dashboard, and daily/monthly leaderboards.

## Included Files
- `app.py`: Flask-SocketIO backend — SQLite persistence, auto-play cycling, monthly question tracking, reveal-answer flow, admin events.
- `data/questions_easy.json`: 320 easy questions.
- `data/questions_medium.json`: 240 medium questions.
- `data/questions_hard.json`: 240 hard questions.
- `data/reserve_questions.json`: unused questions the generator draws from.
- `templates/index.html`: Player interface (phones).
- `templates/display.html`: Stage display for ProPresenter.
- `templates/admin.html`: Admin dashboard (host control).
- `templates/leaderboard.html`: Public leaderboard page.
- `static/style.css`: Shared purple & gold theme.
- `requirements.txt`: Python dependencies.
- `validate.py`: Dev tool — checks all questions have 4 options, a valid answer, no duplicates.
- `add_questions.py`: Dev tool — validates and merges a batch of new questions into the banks.
- `generate_questions.py`: Dev tool — `--total N` adds N questions, split across tiers.

Run `python validate.py` after editing the JSON question banks.

### Adding Questions
To add a batch, just give the total you want:

```bash
python generate_questions.py --total 200   # adds ~80 easy / 60 medium / 60 hard
python validate.py                         # final check
```

The split follows the same 4:3:3 ratio the banks were built with (e.g. 200 →
80/60/60), and questions are pulled from `data/reserve_questions.json`. Anything
already in the banks is skipped automatically, so repeat runs never duplicate. If
the reserve can't cover the request, it prints how many are left and writes
nothing. When the reserve runs low, add more question objects to that file (or
point `--reserve` at a directory of pool files) and run it again.

The banks currently hold **885 questions** (352 easy / 270 medium / 263 hard).

Every question is also **auto-categorized** for the admin's Question Type dropdown,
based on the book named in its `reference` (e.g. `Revelation 21:2` → End Times &
Revelation, `Genesis 3:15` → Genesis & the Law, `Acts 9:25` → Early Church &
Letters). Keep the book name in the reference and any new batch you merge slots
into the right category automatically — nothing extra to tag.

To merge a specific hand-written batch instead, use `add_questions.py` with a file
shaped like this:

```json
{
  "easy":   [{"question": "...", "options": ["A", "B", "C", "D"], "answer": "A", "reference": "Genesis 1:1"}],
  "medium": [],
  "hard":   []
}
```

Then merge it (a flat list of questions each tagged with a `difficulty` works too):

```bash
python add_questions.py new_batch.json --dry-run   # check first, writes nothing
python add_questions.py new_batch.json             # merge
python validate.py                                 # final sanity check
```

The tool refuses to write anything if the batch has a duplicate question (against
the existing banks or within itself), a bad answer, duplicate options, a missing
option, or text over the length limits — so a bad batch can never corrupt the banks.

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
Open `/admin` and enter the admin PIN (set via the `TRIVIA_ADMIN_PIN` environment variable — it is not published anywhere). From there you can:
- ▶️ Force the next question immediately
- 👁️ **Reveal the answer** — the correct option lights up green on every screen, with the verse reference
- 🤖 Toggle auto-play and set the reveal pause
- 🎲 Pick difficulty: Mixed / Easy / Medium / Hard (each tier is picked randomly)
- 📚 Pick a **question type** from the dropdown: 🎲 Mixed (everything), ✝️ Jesus & the Gospels, ⛪ Early Church & Letters, 📜 Genesis & the Law, 🏺 Israel's History, 🔥 Prophets & Prophecy, 📖 End Times & Revelation, or 💡 General Bible Facts — the type is shown as the gold title above each question on every screen
- ⏱️ Set the timer: 15 / 30 / 45 / 60 seconds
- 📊 See question-pool usage for the month
- ⏹️ End the game (scores and used questions are kept)
- 👥 **Players** — see everyone who has ever played, reset one player's scores (frees the name for reuse), or wipe all scores with Fresh Start
- 👑 Crown the **monthly champion** (broadcast to all screens)

### Environment variables (optional)
- `TRIVIA_ADMIN_PIN` — the admin PIN (no default published — set it yourself)
- `TRIVIA_SECRET` — Socket.IO secret key
- `DATABASE_URL` — Postgres connection string (e.g. Neon). When set, scores/settings/winner are stored in Postgres instead of local SQLite.
- `PUBLIC_JOIN_URL` — the URL the stage-display QR code points to (defaults to the deployed Render URL). Players scan this QR to join.

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

## Later: Move to AWS + trivia.westportalchurch.ca (planned — not set up yet)
Everything below is a runbook only. **No AWS account, EC2 instance, or DNS
change has been made** — the app still runs on Render with Neon.

### 1. Launch the EC2 instance
1. AWS Console → EC2 → **Launch instance**
   - AMI: **Ubuntu Server 24.04 LTS**; type: **t2.micro** or **t3.small** (free tier is fine)
   - Create a key pair and keep the `.pem` file safe
2. Security group — allow inbound:
   - SSH (22) from **your IP only**
   - HTTP (80) and HTTPS (443) from **Anywhere**
3. Connect: `ssh -i your-key.pem ubuntu@<ec2-public-ip>`

### 2. Install and run the app
```bash
sudo apt update && sudo apt install -y python3-venv nginx
git clone <your-repo-url> trivia && cd trivia
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Create `/etc/systemd/system/trivia.service`:
```ini
[Unit]
Description=Bible Trivia
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/trivia
Environment=TRIVIA_ADMIN_PIN=choose-a-pin
Environment=PUBLIC_JOIN_URL=https://trivia.westportalchurch.ca/
# No DATABASE_URL on purpose -> uses the local trivia.db (SQLite).
# It is fast, free, and persists on the EBS disk across reboots.
ExecStart=/home/ubuntu/trivia/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable --now trivia
```
The app listens on port 5000 and creates `trivia.db` automatically — no Neon
needed on AWS. (Optional: back the file up nightly, e.g. a cron job that copies
it to S3, so scores can survive even a lost volume.)

### 3. nginx + free HTTPS
`/etc/nginx/sites-available/trivia`:
```nginx
server {
    listen 80;
    server_name trivia.westportalchurch.ca;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;   # required for Socket.IO
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/trivia /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d trivia.westportalchurch.ca
```

### 4. Point the domain at AWS
In the DNS provider that manages `westportalchurch.ca`:
- Add record: **trivia** → **CNAME** → the EC2 public hostname, **or** an
  **A** record → the instance IP. (Allocate an **Elastic IP** first so the
  address never changes when the instance restarts.)
- Wait for propagation (minutes to a few hours), then open
  `https://trivia.westportalchurch.ca/` — the QR code on `/display` will
  already match, via `PUBLIC_JOIN_URL` set in step 2.

### 5. Cutover
- Try a full practice game on AWS before a Sunday service.
- Only after that works well: pause or delete the Render service (keep it as a
  fallback until the first live night on AWS succeeds).
- If you want the old scores, they stay in Neon — copying Postgres → SQLite is
  manual, so simplest is a fresh start (crown/copy monthly champions by hand if
  you care about them).

## Scoring
- **1 point** per correct answer — same for every question, any difficulty
- One answer per player per question
- **Name protection without lockout** — a name can't be doubled while someone is actively playing under it, but reclaiming your own name later always works (even after a server restart). Sessions are remembered per device, so returning players just reappear.
- **Reset tools** — per-player reset, **Reset Month** (wipes the month's scores and question usage; crowned champions are kept), and a full Fresh Start in the admin dashboard

## Question Rules
- Questions are picked **randomly**, per difficulty tier
- The admin's selected **question type** narrows the pool to that category; Mixed draws from all 885
- **No question repeats within a calendar month** (tracked in the DB; survives restarts)
- If a tier runs out mid-month (e.g., all 240 hard questions used), the picker falls back to the other tiers; the month's usage clears on the 1st

## Persistence (survives restarts)
- All answers, scores, daily/monthly boards, and the monthly winner
- Admin settings: difficulty, timer length, auto-play, reveal pause
- The live question and who already answered it — a mid-question restart resumes the same question

## Leaderboards
- **Daily** board resets every day; **monthly** board resets on the 1st
- The crowned monthly champion stays on the leaderboard page banner
