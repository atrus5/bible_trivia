from gevent import monkey
monkey.patch_all()

import os
import json
import math
import time
import random
import sqlite3
from datetime import datetime
from threading import Lock

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'trivia.db')
DATA_DIR = os.path.join(BASE_DIR, 'data')
# NOTE: never hardcode the Neon connection string here — set DATABASE_URL in the
# Render dashboard (or a local .env file, which is gitignored) instead.

# Load a local .env if present (for local testing of DATABASE_URL etc.)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('TRIVIA_SECRET', 'bible-trivia-secret')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

ADMIN_PIN = os.environ.get('TRIVIA_ADMIN_PIN', '5364')
# URL shown in the stage-display QR code. Set PUBLIC_JOIN_URL in Render to your
# onrender.com address; the fallback below keeps local testing working.
JOIN_URL = os.environ.get('PUBLIC_JOIN_URL', 'https://bible-trivia-3jke.onrender.com/')
MULTIPLIER = {'easy': 1, 'medium': 2, 'hard': 3}
DEFAULT_TIMER = 15
DEFAULT_PAUSE = 10         # auto-play: seconds between reveal and next question
DIFFICULTIES = ('easy', 'medium', 'hard')

# ------------------------------------------------------------------
# Question loading (data/*.json)
# ------------------------------------------------------------------
def load_questions():
    qs = []
    for fname, diff in [('questions_easy.json', 'easy'),
                        ('questions_medium.json', 'medium'),
                        ('questions_hard.json', 'hard')]:
        with open(os.path.join(DATA_DIR, fname), encoding='utf-8') as f:
            for i, q in enumerate(json.load(f)):
                q['id'] = f"{diff}-{i}"
                q['difficulty'] = diff
                qs.append(q)
    return qs

QUESTIONS = load_questions()
Q_BY_ID = {q['id']: q for q in QUESTIONS}
POOL_SIZES = {t: sum(1 for q in QUESTIONS if q['difficulty'] == t) for t in DIFFICULTIES}

# ------------------------------------------------------------------
# Database — SQLite by default (local dev); Postgres when DATABASE_URL
# is set (e.g. Neon on Render). The rest of the code stays the same.
# ------------------------------------------------------------------
USE_POSTGRES = bool(os.environ.get('DATABASE_URL'))

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    from contextlib import contextmanager

    _DATABASE_URL = os.environ['DATABASE_URL']
    if 'sslmode=' not in _DATABASE_URL:
        _DATABASE_URL += ('&' if '?' in _DATABASE_URL else '?') + 'sslmode=require'

    class _PgConn:
        """sqlite3-style wrapper over psycopg2 (rows accessible by name)."""
        def __init__(self):
            self._c = psycopg2.connect(_DATABASE_URL)
        def execute(self, query, params=()):
            cur = self._c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(query.replace('?', '%s'), params)
            return cur
        def commit(self): self._c.commit()
        def rollback(self): self._c.rollback()
        def close(self): self._c.close()

    @contextmanager
    def db():
        c = _PgConn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    _ID_COL = 'id SERIAL PRIMARY KEY'
else:
    def db():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    _ID_COL = 'id INTEGER PRIMARY KEY AUTOINCREMENT'

def init_db():
    with db() as conn:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS answers (
            {_ID_COL},
            name TEXT NOT NULL,
            question_id TEXT NOT NULL,
            correct INTEGER NOT NULL,
            points INTEGER NOT NULL,
            ts TEXT NOT NULL)""")
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_answers_name_q
            ON answers(name, question_id)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS monthly_winners (
            month TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            points INTEGER NOT NULL,
            declared_at TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS used_questions (
            question_id TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            month TEXT NOT NULL,
            used_at TEXT NOT NULL,
            UNIQUE(question_id, month))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL)""")

def get_setting(key, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_settings_kv(pairs):
    with db() as conn:
        for k, v in pairs.items():
            conn.execute("""INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (k, str(v)))

def save_answer(name, question_id, correct, points):
    with db() as conn:
        conn.execute("""INSERT INTO answers (name, question_id, correct, points, ts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name, question_id) DO UPDATE SET
                correct=excluded.correct, points=excluded.points""",
            (name, question_id, 1 if correct else 0, points,
             datetime.now().isoformat(timespec='seconds')))

def board(rows):
    return [{"name": r["name"], "score": r["pts"], "correct": r["c"]} for r in rows]

def get_daily_board():
    with db() as conn:
        if USE_POSTGRES:
            rows = conn.execute("""SELECT MIN(name) AS name, SUM(points) pts, SUM(correct) c
                FROM answers WHERE ts::date = CURRENT_DATE
                GROUP BY LOWER(name) ORDER BY pts DESC LIMIT 10""").fetchall()
        else:
            rows = conn.execute("""SELECT name, SUM(points) pts, SUM(correct) c
                FROM answers WHERE date(ts)=date('now','localtime')
                GROUP BY name COLLATE NOCASE ORDER BY pts DESC LIMIT 10""").fetchall()
    return board(rows)

def get_monthly_board():
    with db() as conn:
        if USE_POSTGRES:
            rows = conn.execute("""SELECT MIN(name) AS name, SUM(points) pts, SUM(correct) c
                FROM answers WHERE LEFT(ts, 7) = to_char(now(), 'YYYY-MM')
                GROUP BY LOWER(name) ORDER BY pts DESC LIMIT 10""").fetchall()
        else:
            rows = conn.execute("""SELECT name, SUM(points) pts, SUM(correct) c
                FROM answers WHERE strftime('%Y-%m', ts)=strftime('%Y-%m','now','localtime')
                GROUP BY name COLLATE NOCASE ORDER BY pts DESC LIMIT 10""").fetchall()
    return board(rows)

def get_player_points(name):
    with db() as conn:
        if USE_POSTGRES:
            daily = conn.execute("""SELECT COALESCE(SUM(points),0) p FROM answers
                WHERE LOWER(name)=LOWER(?) AND ts::date = CURRENT_DATE""",
                (name,)).fetchone()["p"]
            monthly = conn.execute("""SELECT COALESCE(SUM(points),0) p FROM answers
                WHERE LOWER(name)=LOWER(?) AND LEFT(ts, 7) = to_char(now(), 'YYYY-MM')""",
                (name,)).fetchone()["p"]
        else:
            daily = conn.execute("""SELECT COALESCE(SUM(points),0) p FROM answers
                WHERE name=? COLLATE NOCASE AND date(ts)=date('now','localtime')""",
                (name,)).fetchone()["p"]
            monthly = conn.execute("""SELECT COALESCE(SUM(points),0) p FROM answers
                WHERE name=? COLLATE NOCASE AND strftime('%Y-%m', ts)=strftime('%Y-%m','now','localtime')""",
                (name,)).fetchone()["p"]
    return daily, monthly

def get_month_winner():
    """Returns the crowned winner for the current month, if the month has been closed."""
    month = datetime.now().strftime('%Y-%m')
    with db() as conn:
        row = conn.execute("SELECT name, points FROM monthly_winners WHERE month=?",
                           (month,)).fetchone()
    return {"month": month, "name": row["name"], "points": row["points"]} if row else None

def current_month():
    return datetime.now().strftime('%Y-%m')

def used_this_month():
    """{difficulty: count} of questions already asked this calendar month."""
    with db() as conn:
        rows = conn.execute("""SELECT difficulty, COUNT(*) c FROM used_questions
            WHERE month=? GROUP BY difficulty""", (current_month(),)).fetchall()
    d = {r["difficulty"]: r["c"] for r in rows}
    return {t: d.get(t, 0) for t in DIFFICULTIES}

# ------------------------------------------------------------------
# Game state (persisted; survives restarts)
# ------------------------------------------------------------------
game = {
    "active": False,
    "question": None,          # current question dict
    "revealed": False,
    "difficulty": "mixed",     # easy | medium | hard | mixed
    "timer_seconds": DEFAULT_TIMER,
    "autoplay": True,          # auto-start next question after the reveal pause
    "pause_seconds": DEFAULT_PAUSE,
    "next_question_at": None,  # wall-clock time when auto-advance should fire
    "paused": False,           # host paused: timer frozen, auto-advance held
    "slide_mode": False,       # ProPresenter mode: one question per slide appearance
}
answered = {}                 # question_id -> set of names that already answered
timer_seconds = DEFAULT_TIMER
timer_running = False
state_lock = Lock()
admins = set()                # sids authenticated as admin
players = {}                  # sid -> name

def public_question(q):
    return {"id": q["id"], "question": q["question"], "options": q["options"],
            "difficulty": q["difficulty"], "total": len(QUESTIONS)}

def pick_question(difficulty):
    """Random question, never repeating within the current calendar month.
    In 'mixed' mode the difficulty tier itself is chosen at random."""
    month = current_month()
    tiers = list(DIFFICULTIES) if difficulty == "mixed" else [difficulty]
    random.shuffle(tiers)
    with db() as conn:
        for tier in tiers:
            used = {r["question_id"] for r in conn.execute(
                """SELECT question_id FROM used_questions
                   WHERE month=? AND difficulty=?""", (month, tier))}
            pool = [q for q in QUESTIONS if q["difficulty"] == tier and q["id"] not in used]
            if pool:
                q = random.choice(pool)
                conn.execute("""INSERT INTO used_questions
                    (question_id, difficulty, month, used_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(question_id, month) DO UPDATE SET used_at=excluded.used_at""",
                    (q["id"], tier, month, datetime.now().isoformat(timespec='seconds')))
                return q
        # Every tier used up this month: clear the month's usage and start over.
        conn.execute("DELETE FROM used_questions WHERE month=?", (month,))
        tier = tiers[0]
        pool = [q for q in QUESTIONS if q["difficulty"] == tier]
        q = random.choice(pool)
        conn.execute("""INSERT INTO used_questions
            (question_id, difficulty, month, used_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(question_id, month) DO UPDATE SET used_at=excluded.used_at""",
            (q["id"], tier, month, datetime.now().isoformat(timespec='seconds')))
        return q

def start_timer():
    global timer_seconds, timer_running
    with state_lock:
        timer_seconds = game.get("timer_seconds", DEFAULT_TIMER)
        timer_running = True
    socketio.emit('timer_tick', {'time_left': timer_seconds, 'active': True,
                                 'total': timer_seconds})

def timer_background_task():
    """Ticks the countdown each second; auto-reveals at zero, then auto-advances
    to the next question after the configured pause (auto-play mode).
    While paused, the countdown freezes and auto-advance is held."""
    global timer_seconds, timer_running
    while True:
        socketio.sleep(1)
        reveal_now = False
        auto_now = False
        pause_left = None
        with state_lock:
            paused = game["paused"]
            if not paused:
                if timer_running and timer_seconds > 0:
                    timer_seconds -= 1
                    if timer_seconds == 0:
                        timer_running = False
                        reveal_now = True
                if (game["active"] and game["revealed"] and game["autoplay"]
                        and not game.get("slide_mode") and game.get("next_question_at")):
                    pause_left = game["next_question_at"] - time.time()
                    if pause_left <= 0:
                        auto_now = True

        # Per-second countdown broadcast (while a question is running or paused)
        if timer_running or reveal_now or paused:
            socketio.emit('timer_tick', {'time_left': timer_seconds, 'active': timer_running,
                                         'total': game.get("timer_seconds", DEFAULT_TIMER),
                                         'paused': paused})

        if reveal_now:
            reveal_answer()
        elif pause_left is not None and not auto_now:
            socketio.emit('next_question_countdown',
                          {"seconds": max(0, math.ceil(pause_left))})
        if auto_now:
            start_next_question()


def set_paused(value):
    """Freeze or resume the game: timer stops, auto-advance is held, and
    answering is locked — the current question itself stays live."""
    global timer_seconds, timer_running
    with state_lock:
        game["paused"] = bool(value)
        if game["paused"]:
            game["next_question_at"] = None  # hold auto-advance
        elif game["active"] and game["revealed"] and game["autoplay"]:
            game["next_question_at"] = time.time() + game["pause_seconds"]
    socketio.emit('game_paused', {'paused': game["paused"]})
    socketio.emit('timer_tick', {'time_left': timer_seconds, 'active': timer_running,
                                 'total': game.get("timer_seconds", DEFAULT_TIMER),
                                 'paused': game["paused"]})
    push_admin_state()
    save_state()

def start_next_question():
    q = pick_question(game["difficulty"])
    if not q:
        return
    game["active"] = True
    game["question"] = q
    game["revealed"] = False
    game["next_question_at"] = None
    game["paused"] = False
    answered[q["id"]] = set()
    socketio.emit('game_status', {'active': True})
    socketio.emit('new_question', public_question(q))
    start_timer()
    push_admin_state()
    save_state()

# ------------------------------------------------------------------
# State persistence (settings + live game survive restarts)
# ------------------------------------------------------------------
def save_state():
    set_settings_kv({
        "active": "1" if game["active"] else "0",
        "current_question_id": game["question"]["id"] if game["question"] else "",
        "revealed": "1" if game["revealed"] else "0",
        "difficulty": game["difficulty"],
        "timer_seconds": game["timer_seconds"],
        "autoplay": "1" if game["autoplay"] else "0",
        "pause_seconds": game["pause_seconds"],
        "paused": "1" if game["paused"] else "0",
        "slide_mode": "1" if game["slide_mode"] else "0",
    })

def restore_state():
    game["difficulty"] = get_setting("difficulty", "mixed")
    game["timer_seconds"] = int(get_setting("timer_seconds", DEFAULT_TIMER))
    game["autoplay"] = get_setting("autoplay", "1") == "1"
    game["pause_seconds"] = int(get_setting("pause_seconds", DEFAULT_PAUSE))
    game["paused"] = get_setting("paused", "0") == "1"
    game["slide_mode"] = get_setting("slide_mode", "0") == "1"
    if get_setting("active", "0") == "1":
        q = Q_BY_ID.get(get_setting("current_question_id", ""))
        if q:
            game["active"] = True
            game["question"] = q
            game["revealed"] = get_setting("revealed", "0") == "1"
            # Rebuild who already answered this question from the answers table
            with db() as conn:
                rows = conn.execute("SELECT name FROM answers WHERE question_id=?",
                                    (q["id"],)).fetchall()
            answered[q["id"]] = {r["name"] for r in rows}
            if game["revealed"] and game["autoplay"] and not game["paused"]:
                game["next_question_at"] = time.time() + game["pause_seconds"]
    global timer_seconds, timer_running
    timer_seconds = game["timer_seconds"]
    timer_running = game["active"] and not game["revealed"]

# ------------------------------------------------------------------
# Broadcast helpers
# ------------------------------------------------------------------
def push_leaderboard():
    socketio.emit('update_leaderboard', get_daily_board())

def push_admin_state():
    q = game["question"]
    socketio.emit('admin_state', {
        "active": game["active"],
        "revealed": game["revealed"],
        "paused": game["paused"],
        "slide_mode": game["slide_mode"],
        "difficulty": game["difficulty"],
        "timer_seconds": game.get("timer_seconds", DEFAULT_TIMER),
        "autoplay": game["autoplay"],
        "pause_seconds": game["pause_seconds"],
        "used": used_this_month(),
        "pool": POOL_SIZES,
        "month_label": datetime.now().strftime('%B %Y'),
        "question": public_question(q) if q else None,
        "answer": q["answer"] if q else None,
        "reference": q.get("reference", "") if q else "",
        "answered_count": len(answered.get(q["id"], set())) if q else 0,
        "player_count": len(players),
    })

def reveal_answer():
    """Show the correct answer on every screen and lock further input."""
    q = game["question"]
    if not q or game["revealed"]:
        return
    game["revealed"] = True
    next_in = 0
    if game["autoplay"] and not game.get("slide_mode"):
        game["next_question_at"] = time.time() + game["pause_seconds"]
        next_in = game["pause_seconds"]
    socketio.emit('reveal_answer', {
        "id": q["id"], "answer": q["answer"], "reference": q.get("reference", ""),
        "next_in": next_in
    })
    push_leaderboard()
    push_admin_state()
    save_state()

def reset_game():
    game["active"] = False
    game["question"] = None
    game["revealed"] = False
    game["next_question_at"] = None
    game["paused"] = False
    answered.clear()
    socketio.emit('game_status', {'active': False,
                                  'message': 'The game is starting soon...'})
    push_admin_state()
    save_state()

# ------------------------------------------------------------------
# HTTP routes
# ------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/display')
def display():
    return render_template('display.html', join_url=JOIN_URL)

@app.route('/admin')
def admin():
    return render_template('admin.html', pin_length=len(ADMIN_PIN))

@app.route('/leaderboard')
def leaderboard():
    return render_template('leaderboard.html')

@app.route('/api/status')
def status():
    return jsonify({"active": game["active"], "players": len(players),
                    "questions": len(QUESTIONS)})

@app.route('/propresenter_start')
def propresenter_start():
    # The stage display loads this whenever ProPresenter shows the web slide.
    # It never resets anything — the display re-syncs over Socket.IO on connect.
    return {"status": "ok"}, 200

# ------------------------------------------------------------------
# Sync anyone who connects mid-game (ProPresenter reloads, late joiners)
# ------------------------------------------------------------------
@socketio.on('connect')
def handle_connect():
    if game["active"] and game["question"]:
        emit('game_status', {'active': True})
        emit('new_question', public_question(game["question"]))
        emit('timer_tick', {'time_left': timer_seconds, 'active': timer_running,
                            'total': game.get("timer_seconds", DEFAULT_TIMER),
                            'paused': game["paused"]})
        if game["revealed"]:
            next_in = (max(0, math.ceil(game["next_question_at"] - time.time()))
                       if game.get("next_question_at") else 0)
            emit('reveal_answer', {"id": game["question"]["id"],
                                   "answer": game["question"]["answer"],
                                   "reference": game["question"].get("reference", ""),
                                   "next_in": next_in})
            if game["autoplay"] and next_in:
                emit('next_question_countdown', {"seconds": next_in})
    else:
        emit('game_status', {'active': False,
                             'message': 'The game is starting soon...'})

# ------------------------------------------------------------------
# ProPresenter slide mode: exactly one question per slide appearance
# ------------------------------------------------------------------
_last_slide_start = 0.0

@socketio.on('slide_shown')
def handle_slide_shown(_data=None):
    """The stage display emits this whenever ProPresenter (re)loads or re-shows
    the web slide. In slide mode each appearance shows exactly one question;
    the reveal just holds on screen until the slide comes around again."""
    global _last_slide_start
    if not game.get("slide_mode") or game["paused"]:
        return
    if game["active"] and game["question"] and not game["revealed"]:
        return  # a live unrevealed question is on screen — just resync
    now = time.time()
    if now - _last_slide_start < 3:
        return  # debounce duplicate show events (connect + visibilitychange)
    _last_slide_start = now
    start_next_question()

# ------------------------------------------------------------------
# Player events
# ------------------------------------------------------------------
@socketio.on('login')
def handle_login(data):
    name = (data.get('name') or 'Anonymous').strip()[:24] or 'Anonymous'
    players[request.sid] = name
    daily, monthly = get_player_points(name)
    emit('score_update', {'daily': daily, 'monthly': monthly})
    push_leaderboard()
    push_admin_state()
    if game["active"] and game["question"]:
        emit('game_status', {'active': True})
        emit('new_question', public_question(game["question"]))
        emit('timer_tick', {'time_left': timer_seconds, 'active': timer_running,
                            'total': game.get("timer_seconds", DEFAULT_TIMER),
                            'paused': game["paused"]})
        if game["revealed"]:
            next_in = (max(0, math.ceil(game["next_question_at"] - time.time()))
                       if game.get("next_question_at") else 0)
            emit('reveal_answer', {"id": game["question"]["id"],
                                   "answer": game["question"]["answer"],
                                   "reference": game["question"].get("reference", ""),
                                   "next_in": next_in})
    else:
        emit('game_status', {'active': False,
                             'message': 'The game is starting soon...'})

@socketio.on('submit_answer')
def handle_answer(data):
    sid = request.sid
    name = players.get(sid)
    q = game["question"]
    if not name or not q or game["revealed"]:
        emit('answer_result', {'correct': False, 'locked': True,
                               'message': "Answering is closed."})
        return
    if name in answered.get(q["id"], set()):
        emit('answer_result', {'correct': False, 'locked': True,
                               'message': "You already answered!"})
        return
    rejected = None
    with state_lock:
        if timer_seconds <= 0 or not timer_running:
            rejected = "Time's up! Answer locked."
        elif game["paused"]:
            rejected = "The game is paused — answering is closed."
        else:
            time_left = timer_seconds
    if rejected:
        # NOTE: never emit while holding state_lock — it stalls the timer loop
        emit('answer_result', {'correct': False, 'locked': True,
                               'message': rejected})
        return

    selected = data.get('option')
    correct = selected == q["answer"]
    points = (10 + time_left) * MULTIPLIER.get(q["difficulty"], 1) if correct else 0

    answered.setdefault(q["id"], set()).add(name)
    save_answer(name, q["id"], correct, points)

    daily, monthly = get_player_points(name)
    emit('answer_result', {'correct': correct, 'score': points,
                           'daily': daily, 'monthly': monthly,
                           'message': "Correct! 🎉" if correct else "Not this time — stay tuned!"})
    push_leaderboard()
    push_admin_state()

@socketio.on('request_leaderboard')
def handle_request_leaderboard(_data=None):
    emit('leaderboard_data', {
        "daily": get_daily_board(),
        "monthly": get_monthly_board(),
        "winner": get_month_winner(),
        "month_label": datetime.now().strftime('%B %Y'),
    })

# ------------------------------------------------------------------
# Admin events
# ------------------------------------------------------------------
def admin_only(handler):
    def wrapped(data=None):
        if request.sid not in admins:
            emit('admin_error', {'message': 'Not authorized. Enter the PIN first.'})
            return
        return handler(data or {})
    wrapped.__name__ = handler.__name__
    return wrapped

@socketio.on('admin_login')
def handle_admin_login(data):
    if data.get('pin') == ADMIN_PIN:
        admins.add(request.sid)
        emit('admin_ok', {})
        push_admin_state()
    else:
        emit('admin_error', {'message': 'Wrong PIN.'})

@socketio.on('admin_start')
@admin_only
def handle_admin_start(_data):
    if game["paused"]:
        set_paused(False)
    if not (game["active"] and game["question"]):
        start_next_question()
    else:
        push_admin_state()

@socketio.on('admin_pause')
@admin_only
def handle_admin_pause(_data):
    set_paused(not game["paused"])

@socketio.on('admin_next_question')
@admin_only
def handle_admin_next(_data):
    if game["paused"]:
        set_paused(False)
    start_next_question()

@socketio.on('admin_reveal')
@admin_only
def handle_admin_reveal(_data):
    if game["paused"]:
        set_paused(False)
    reveal_answer()

@socketio.on('admin_set_difficulty')
@admin_only
def handle_admin_set_difficulty(data):
    diff = data.get('difficulty')
    if diff in ('easy', 'medium', 'hard', 'mixed'):
        game["difficulty"] = diff
        save_state()
        push_admin_state()

@socketio.on('admin_set_timer')
@admin_only
def handle_admin_set_timer(data):
    secs = data.get('seconds')
    if secs in (15, 30, 45, 60):
        game["timer_seconds"] = secs
        save_state()
        push_admin_state()

@socketio.on('admin_toggle_autoplay')
@admin_only
def handle_admin_toggle_autoplay(_data):
    game["autoplay"] = not game["autoplay"]
    if game["autoplay"] and game["revealed"] and game["active"]:
        game["next_question_at"] = time.time() + game["pause_seconds"]
    else:
        game["next_question_at"] = None
    save_state()
    push_admin_state()

@socketio.on('admin_set_pause')
@admin_only
def handle_admin_set_pause(data):
    secs = data.get('seconds')
    if secs in (5, 10, 15, 20):
        game["pause_seconds"] = secs
        if game.get("next_question_at"):
            game["next_question_at"] = time.time() + secs
        save_state()
        push_admin_state()

@socketio.on('admin_toggle_slide_mode')
@admin_only
def handle_admin_toggle_slide_mode(_data):
    game["slide_mode"] = not game["slide_mode"]
    if game["slide_mode"]:
        game["next_question_at"] = None  # suspend the continuous auto-advance
    save_state()
    push_admin_state()

@socketio.on('admin_end_game')
@admin_only
def handle_admin_end(_data):
    reset_game()

@socketio.on('admin_end_month')
@admin_only
def handle_admin_end_month(_data):
    monthly = get_monthly_board()
    if monthly:
        winner = monthly[0]
        month = current_month()
        with db() as conn:
            conn.execute("""INSERT INTO monthly_winners (month, name, points, declared_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(month) DO UPDATE SET name=excluded.name,
                    points=excluded.points, declared_at=excluded.declared_at""",
                (month, winner["name"], winner["score"],
                 datetime.now().isoformat(timespec='seconds')))
        socketio.emit('month_crowned', {"name": winner["name"],
                                        "points": winner["score"],
                                        "month_label": datetime.now().strftime('%B %Y')})
        push_admin_state()
    else:
        emit('admin_error', {'message': 'No scores this month yet.'})

# ------------------------------------------------------------------
# Disconnect cleanup
# ------------------------------------------------------------------
@socketio.on('disconnect')
def handle_disconnect():
    players.pop(request.sid, None)
    admins.discard(request.sid)
    push_admin_state()

# ------------------------------------------------------------------
# Boot: init DB, restore last state, start the timer loop
# ------------------------------------------------------------------
init_db()
restore_state()
socketio.start_background_task(timer_background_task)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)),
                 debug=False, allow_unsafe_werkzeug=True)
