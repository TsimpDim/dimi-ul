import os
import json
import sqlite3
import secrets
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, session, jsonify, render_template, redirect, url_for, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "templates.json")
DB_PATH = os.path.join(BASE_DIR, "dimi_ul.db")

DEFAULT_VALUE = {"reps": 8, "seconds": 30}

# Demo seed data: (template_id, days_ago, progression_index)
DEMO_SESSIONS = [
    ("upper_a", 28, 0),
    ("lower_a", 24, 0),
    ("upper_b", 19, 0),
    ("lower_b", 14, 0),
    ("upper_a", 7, 1),
]

DEMO_BASE_WEIGHT = {
    "upper_a": {
        "Incline Dumbbell Press": 22.0,
        "Chest-Supported T-Bar Row": 40.0,
        "Weighted Dips": 10.0,
        "Neutral Grip Pull-Ups": None,
        "Overhead Cable Tricep Extension": 25.0,
        "Incline Dumbbell Curl": 12.0,
    },
    "lower_a": {
        "Back Squats": 80.0,
        "Bulgarian Split Squats": 20.0,
        "Leg Press": 120.0,
        "Standing Calf Raises": 40.0,
        "Strict Hanging Leg Raises": None,
    },
    "upper_b": {
        "Seated Dumbbell Press": 22.0,
        "Wide-Grip Lat Pulldown": 50.0,
        "Cable Lateral Raises": 8.0,
        "Face Pulls": 20.0,
        "EZ Bar Skull Crushers": 25.0,
        "Hammer Curls": 12.0,
    },
    "lower_b": {
        "Romanian Deadlifts (RDLs)": 90.0,
        "Leg Extensions": 45.0,
        "Seated Hamstring Curls": 35.0,
        "Heavy Farmer's Walks": 28.0,
        "Seated Calf Raises": 50.0,
        "Heavy Cable Crunches": 30.0,
    },
}


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

app = Flask(__name__)


def get_secret_key():
    key_file = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(key_file):
        with open(key_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as f:
        f.write(key)
    return key


app.secret_key = get_secret_key()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exercise_memory (
    user_id INTEGER NOT NULL,
    exercise_name TEXT NOT NULL,
    last_weight REAL,
    last_reps INTEGER,
    PRIMARY KEY (user_id, exercise_name)
);
CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    template_id TEXT NOT NULL,
    template_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS workout_exercises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL,
    exercise_name TEXT NOT NULL,
    block TEXT,
    metric TEXT NOT NULL DEFAULT 'reps',
    notes TEXT,
    sets_reps TEXT,
    position INTEGER NOT NULL,
    sets INTEGER NOT NULL DEFAULT 3,
    reps INTEGER,
    weight REAL,
    completed INTEGER NOT NULL DEFAULT 0,
    added_from_pool INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript(SCHEMA)


def seed_demo():
    if os.environ.get("SEED_DEMO", "1") != "1":
        return
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        row = db.execute("SELECT id FROM users WHERE username='test'").fetchone()
        if row is None:
            db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?,?)",
                ("test", generate_password_hash("test")),
            )
            uid = db.execute(
                "SELECT id FROM users WHERE username='test'"
            ).fetchone()["id"]
        else:
            uid = row["id"]

        count = db.execute(
            "SELECT COUNT(*) AS c FROM workouts WHERE user_id=?", (uid,)
        ).fetchone()["c"]
        if count:
            db.commit()
            return

        now = datetime.now(timezone.utc)

        def insert_exercise(wid, ex, position, weight, value, completed):
            db.execute(
                "INSERT INTO workout_exercises (workout_id, exercise_name, block, metric, notes, sets_reps, position, sets, reps, weight, completed) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    wid,
                    ex["name"],
                    ex["block"],
                    ex["metric"],
                    ex.get("notes"),
                    ex.get("sets_reps"),
                    position,
                    3,
                    value,
                    weight,
                    completed,
                ),
            )
            set_memory(
                db, uid, ex["name"], weight=weight, reps=value,
                weight_set=True, reps_set=True,
            )

        for template_id, days_ago, prog in DEMO_SESSIONS:
            t = find_template(template_id)
            created = now - timedelta(days=days_ago)
            cur = db.execute(
                "INSERT INTO workouts (user_id, template_id, template_name, created_at, completed_at) VALUES (?,?,?,?,?)",
                (uid, t["id"], t["name"], created.isoformat(timespec="seconds"), created.isoformat(timespec="seconds")),
            )
            wid = cur.lastrowid
            for i, ex in enumerate(t["exercises"]):
                base = DEMO_BASE_WEIGHT.get(template_id, {}).get(ex["name"])
                weight = None if base is None else round(base * (1 + 0.1 * prog), 1)
                value = 30 if ex["metric"] == "seconds" else 8
                insert_exercise(wid, ex, i, weight, value, 1)

        # Active, semi-completed workout from the most recent template session.
        t = find_template("upper_a")
        created = now
        cur = db.execute(
            "INSERT INTO workouts (user_id, template_id, template_name, created_at, completed_at) VALUES (?,?,?,?,?)",
            (uid, "upper_a", t["name"], created.isoformat(timespec="seconds"), None),
        )
        wid = cur.lastrowid
        for i, ex in enumerate(t["exercises"]):
            base = DEMO_BASE_WEIGHT["upper_a"].get(ex["name"])
            weight = None if base is None else round(base * 1.1, 1)
            value = 8
            insert_exercise(wid, ex, i, weight, value, 1 if i < 3 else 0)

        db.commit()
    finally:
        db.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "unauthorized"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return wrapper


def find_template(template_id):
    for t in CONFIG["templates"]:
        if t["id"] == template_id:
            return t
    return None


def find_pool(pool_id):
    for p in CONFIG["pools"]:
        if p["id"] == pool_id:
            return p
    return None


def get_memory(db, user_id, exercise_name):
    row = db.execute(
        "SELECT last_weight, last_reps FROM exercise_memory WHERE user_id=? AND exercise_name=?",
        (user_id, exercise_name),
    ).fetchone()
    return row


def set_memory(db, user_id, exercise_name, weight=None, reps=None, weight_set=False, reps_set=False):
    row = db.execute(
        "SELECT 1 FROM exercise_memory WHERE user_id=? AND exercise_name=?",
        (user_id, exercise_name),
    ).fetchone()
    if row:
        sets, vals = [], []
        if weight_set:
            sets.append("last_weight=?")
            vals.append(weight)
        if reps_set:
            sets.append("last_reps=?")
            vals.append(reps)
        if sets:
            vals += [user_id, exercise_name]
            db.execute(
                f"UPDATE exercise_memory SET {', '.join(sets)} WHERE user_id=? AND exercise_name=?",
                vals,
            )
    else:
        w = weight if weight_set else None
        r = reps if reps_set else None
        db.execute(
            "INSERT INTO exercise_memory (user_id, exercise_name, last_weight, last_reps) VALUES (?,?,?,?)",
            (user_id, exercise_name, w, r),
        )


def exercise_dict(row):
    return {
        "id": row["id"],
        "name": row["exercise_name"],
        "block": row["block"],
        "metric": row["metric"],
        "notes": row["notes"],
        "sets_reps": row["sets_reps"],
        "sets": row["sets"],
        "reps": row["reps"],
        "weight": row["weight"],
        "completed": bool(row["completed"]),
        "added_from_pool": bool(row["added_from_pool"]),
    }


def workout_detail(workout):
    db = get_db()
    exercises = [
        exercise_dict(r)
        for r in db.execute(
            "SELECT * FROM workout_exercises WHERE workout_id=? ORDER BY position",
            (workout["id"],),
        ).fetchall()
    ]
    total = len(exercises)
    done = sum(1 for e in exercises if e["completed"])
    return {
        "id": workout["id"],
        "template_id": workout["template_id"],
        "template_name": workout["template_name"],
        "created_at": workout["created_at"],
        "completed_at": workout["completed_at"],
        "done": done,
        "total": total,
        "exercises": exercises,
    }


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", app_name=CONFIG["app_name"])


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        error = None
        if not username or not password:
            error = "Username and password are required."
        elif len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 4:
            error = "Password must be at least 4 characters."
        if error is None:
            db = get_db()
            exists = db.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone()
            if exists:
                error = "That username is already taken."
            else:
                db.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?,?)",
                    (username, generate_password_hash(password)),
                )
                db.commit()
                user = db.execute(
                    "SELECT id FROM users WHERE username=?", (username,)
                ).fetchone()
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
        return render_template("register.html", error=error, username=username)
    return render_template("register.html", error=None, username="")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            return render_template("login.html", error="Invalid username or password.", username=username)
        session["user_id"] = user["id"]
        return redirect(url_for("index"))
    return render_template("login.html", error=None, username="")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.route("/api/config")
@login_required
def api_config():
    return jsonify(CONFIG)


@app.route("/api/workouts/active")
@login_required
def api_active():
    db = get_db()
    row = db.execute(
        "SELECT * FROM workouts WHERE user_id=? AND completed_at IS NULL ORDER BY id DESC LIMIT 1",
        (session["user_id"],),
    ).fetchone()
    if row is None:
        return jsonify({"active": None})
    return jsonify({"active": workout_detail(row)})


@app.route("/api/workouts", methods=["POST"])
@login_required
def api_create_workout():
    db = get_db()
    user_id = session["user_id"]
    data = request.get_json(silent=True) or {}
    template_id = data.get("template_id")
    template = find_template(template_id)
    if template is None:
        return jsonify({"error": "Unknown template."}), 400

    active = db.execute(
        "SELECT id FROM workouts WHERE user_id=? AND completed_at IS NULL",
        (user_id,),
    ).fetchone()
    if active:
        return jsonify({"error": "You already have an active workout.", "workout_id": active["id"]}), 409

    created = now_iso()
    cur = db.execute(
        "INSERT INTO workouts (user_id, template_id, template_name, created_at) VALUES (?,?,?,?)",
        (user_id, template["id"], template["name"], created),
    )
    workout_id = cur.lastrowid
    for i, ex in enumerate(template["exercises"]):
        mem = get_memory(db, user_id, ex["name"])
        reps = mem["last_reps"] if mem and mem["last_reps"] is not None else DEFAULT_VALUE[ex["metric"]]
        weight = mem["last_weight"] if mem else None
        db.execute(
            "INSERT INTO workout_exercises (workout_id, exercise_name, block, metric, notes, sets_reps, position, sets, reps, weight) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (workout_id, ex["name"], ex["block"], ex["metric"], ex.get("notes"), ex.get("sets_reps"), i, 3, reps, weight),
        )
    db.commit()
    row = db.execute("SELECT * FROM workouts WHERE id=?", (workout_id,)).fetchone()
    return jsonify(workout_detail(row)), 201


@app.route("/api/workouts/<int:wid>")
@login_required
def api_workout(wid):
    db = get_db()
    row = db.execute(
        "SELECT * FROM workouts WHERE id=? AND user_id=?", (wid, session["user_id"])
    ).fetchone()
    if row is None:
        return jsonify({"error": "Not found."}), 404
    return jsonify(workout_detail(row))


@app.route("/api/workouts/<int:wid>/exercises/<int:eid>", methods=["PATCH"])
@login_required
def api_patch_exercise(wid, eid):
    db = get_db()
    user_id = session["user_id"]
    row = db.execute(
        "SELECT * FROM workout_exercises WHERE id=? AND workout_id=?",
        (eid, wid),
    ).fetchone()
    if row is None:
        return jsonify({"error": "Not found."}), 404
    wrow = db.execute(
        "SELECT 1 FROM workouts WHERE id=? AND user_id=?", (wid, user_id)
    ).fetchone()
    if wrow is None:
        return jsonify({"error": "Not found."}), 404

    data = request.get_json(silent=True) or {}
    sets, cols, vals = [], [], []

    def add(col, value):
        cols.append(f"{col}=?")
        vals.append(value)

    if "sets" in data:
        add("sets", max(1, int(data["sets"])))
    if "reps" in data:
        r = data["reps"]
        r = None if r in (None, "") else int(r)
        add("reps", r)
        set_memory(db, user_id, row["exercise_name"], reps=r, reps_set=True)
    if "weight" in data:
        w = data["weight"]
        w = None if w in (None, "") else float(w)
        add("weight", w)
        set_memory(db, user_id, row["exercise_name"], weight=w, weight_set=True)
    if "completed" in data:
        add("completed", 1 if data["completed"] else 0)

    if cols:
        vals += [eid]
        db.execute(
            f"UPDATE workout_exercises SET {', '.join(cols)} WHERE id=?", vals
        )
    db.commit()
    new_row = db.execute(
        "SELECT * FROM workout_exercises WHERE id=?", (eid,)
    ).fetchone()
    return jsonify(exercise_dict(new_row))


@app.route("/api/workouts/<int:wid>/exercises", methods=["POST"])
@login_required
def api_add_exercise(wid):
    db = get_db()
    user_id = session["user_id"]
    wrow = db.execute(
        "SELECT * FROM workouts WHERE id=? AND user_id=?", (wid, user_id)
    ).fetchone()
    if wrow is None:
        return jsonify({"error": "Not found."}), 404
    if wrow["completed_at"] is not None:
        return jsonify({"error": "Workout is already finished."}), 400

    data = request.get_json(silent=True) or {}
    pool_id = data.get("pool_id")
    exercise_name = (data.get("exercise_name") or "").strip()
    pool = find_pool(pool_id)
    if pool is None:
        return jsonify({"error": "Unknown pool."}), 400
    target = next((e for e in pool["exercises"] if e["name"] == exercise_name), None)
    if target is None:
        return jsonify({"error": "Exercise not in this pool."}), 400

    max_pos = db.execute(
        "SELECT COALESCE(MAX(position), -1) AS m FROM workout_exercises WHERE workout_id=?",
        (wid,),
    ).fetchone()["m"]
    mem = get_memory(db, user_id, exercise_name)
    reps = mem["last_reps"] if mem and mem["last_reps"] is not None else DEFAULT_VALUE[target["metric"]]
    weight = mem["last_weight"] if mem else None
    cur = db.execute(
        "INSERT INTO workout_exercises (workout_id, exercise_name, block, metric, position, sets, reps, weight, added_from_pool) VALUES (?,?,?,?,?,?,?,?,1)",
        (wid, exercise_name, pool["name"], target["metric"], max_pos + 1, 3, reps, weight),
    )
    db.commit()
    new_row = db.execute(
        "SELECT * FROM workout_exercises WHERE id=?", (cur.lastrowid,)
    ).fetchone()
    return jsonify(exercise_dict(new_row)), 201


@app.route("/api/workouts/<int:wid>/exercises/<int:eid>", methods=["DELETE"])
@login_required
def api_delete_exercise(wid, eid):
    db = get_db()
    user_id = session["user_id"]
    wrow = db.execute(
        "SELECT * FROM workouts WHERE id=? AND user_id=?", (wid, user_id)
    ).fetchone()
    if wrow is None:
        return jsonify({"error": "Not found."}), 404
    if wrow["completed_at"] is not None:
        return jsonify({"error": "Workout is already finished."}), 400
    db.execute(
        "DELETE FROM workout_exercises WHERE id=? AND workout_id=?", (eid, wid)
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/workouts/<int:wid>/finish", methods=["POST"])
@login_required
def api_finish_workout(wid):
    db = get_db()
    user_id = session["user_id"]
    wrow = db.execute(
        "SELECT * FROM workouts WHERE id=? AND user_id=?", (wid, user_id)
    ).fetchone()
    if wrow is None:
        return jsonify({"error": "Not found."}), 404
    db.execute(
        "UPDATE workouts SET completed_at=? WHERE id=?", (now_iso(), wid)
    )
    db.commit()
    row = db.execute("SELECT * FROM workouts WHERE id=?", (wid,)).fetchone()
    return jsonify(workout_detail(row))


@app.route("/api/workouts/<int:wid>", methods=["DELETE"])
@login_required
def api_discard_workout(wid):
    db = get_db()
    user_id = session["user_id"]
    wrow = db.execute(
        "SELECT * FROM workouts WHERE id=? AND user_id=?", (wid, user_id)
    ).fetchone()
    if wrow is None:
        return jsonify({"error": "Not found."}), 404
    db.execute("DELETE FROM workouts WHERE id=?", (wid,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/last-per-template")
@login_required
def api_last_per_template():
    db = get_db()
    user_id = session["user_id"]
    rows = db.execute(
        """
        SELECT template_id, MAX(completed_at) AS last
        FROM workouts
        WHERE user_id=? AND completed_at IS NOT NULL
        GROUP BY template_id
        """,
        (user_id,),
    ).fetchall()
    return jsonify({r["template_id"]: r["last"] for r in rows})


@app.route("/api/log")
@login_required
def api_log():
    db = get_db()
    user_id = session["user_id"]
    rows = db.execute(
        "SELECT * FROM workouts WHERE user_id=? AND completed_at IS NOT NULL ORDER BY completed_at DESC",
        (user_id,),
    ).fetchall()
    return jsonify([workout_detail(r) for r in rows])


@app.route("/api/analytics")
@login_required
def api_analytics():
    db = get_db()
    user_id = session["user_id"]

    rows = db.execute(
        """
        SELECT w.id AS workout_id, w.template_name, w.completed_at,
               e.exercise_name, e.metric, e.sets, e.reps, e.weight, e.completed
        FROM workout_exercises e
        JOIN workouts w ON w.id = e.workout_id
        WHERE w.user_id=? AND w.completed_at IS NOT NULL AND e.completed = 1
        ORDER BY w.completed_at ASC, e.position ASC
        """,
        (user_id,),
    ).fetchall()

    def day(iso):
        try:
            return iso[:10]
        except (TypeError, IndexError):
            return ""

    one_rm = {}
    weight_prog = {}
    volume = {}
    exercise_set = {}

    for r in rows:
        name = r["exercise_name"]
        metric = r["metric"]
        d = day(r["completed_at"])
        exercise_set.setdefault(name, metric)

        w = r["weight"]
        reps = r["reps"]
        sets = r["sets"] or 0

        if w is not None:
            weight_prog.setdefault(name, []).append({"date": d, "weight": w})
            if metric == "reps" and reps:
                e1rm = round(w * (1 + reps / 30.0), 1)
                one_rm.setdefault(name, []).append(
                    {"date": d, "weight": w, "reps": reps, "e1rm": e1rm}
                )

        key = (r["workout_id"], r["completed_at"])
        vol = volume.setdefault(
            key,
            {
                "workout_id": r["workout_id"],
                "date": d,
                "template_name": r["template_name"],
                "tonnage": 0.0,
                "total_reps": 0,
                "total_sets": 0,
            },
        )
        vol["total_sets"] += sets
        if reps:
            vol["total_reps"] += reps
        if w is not None and reps:
            vol["tonnage"] += sets * reps * w

    volume_list = list(volume.values())
    volume_list.sort(key=lambda v: v["date"])
    for v in volume_list:
        v["tonnage"] = round(v["tonnage"], 1)
        v["label"] = v["date"]

    # Workout frequency and template breakdown from the workouts table.
    week_counts = {}
    template_counts = {}
    wrows = db.execute(
        "SELECT completed_at, template_name FROM workouts WHERE user_id=? AND completed_at IS NOT NULL",
        (user_id,),
    ).fetchall()
    for wrow in wrows:
        template_counts[wrow["template_name"]] = (
            template_counts.get(wrow["template_name"], 0) + 1
        )
        d = day(wrow["completed_at"])
        try:
            dt = datetime.fromisoformat(d)
        except ValueError:
            continue
        iso = dt.isocalendar()
        week_counts[(iso[0], iso[1])] = week_counts.get((iso[0], iso[1]), 0) + 1
    frequency = [
        {"week": f"{y}-W{w:02d}", "label": f"W{w:02d}", "count": c}
        for (y, w), c in sorted(week_counts.items())
    ]

    prs = []
    for name, metric in exercise_set.items():
        pts = [r for r in rows if r["exercise_name"] == name]
        weights = [r["weight"] for r in pts if r["weight"] is not None]
        values = [r["reps"] for r in pts if r["reps"] is not None]
        best_e1rm = None
        for r in pts:
            if r["metric"] == "reps" and r["weight"] is not None and r["reps"]:
                e = round(r["weight"] * (1 + r["reps"] / 30.0), 1)
                best_e1rm = e if best_e1rm is None or e > best_e1rm else best_e1rm
        prs.append(
            {
                "name": name,
                "metric": metric,
                "max_weight": max(weights) if weights else None,
                "max_value": max(values) if values else None,
                "best_e1rm": best_e1rm,
            }
        )
    prs.sort(key=lambda p: p["name"].lower())

    totals_workouts = db.execute(
        "SELECT COUNT(*) AS c FROM workouts WHERE user_id=? AND completed_at IS NOT NULL",
        (user_id,),
    ).fetchone()["c"]

    return jsonify(
        {
            "totals": {
                "workouts": totals_workouts,
                "exercises": len(rows),
            },
            "exercises": [{"name": n, "metric": m} for n, m in exercise_set.items()],
            "one_rm": one_rm,
            "weight": weight_prog,
            "volume": volume_list,
            "frequency": frequency,
            "template_counts": [
                {"name": n, "count": c} for n, c in template_counts.items()
            ],
            "prs": prs,
        }
    )


init_db()
seed_demo()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=True)
