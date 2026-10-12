# Dimi UL

A mobile-first workout logger for an Upper/Lower training split. Built with Flask + SQLite and a vanilla-JS frontend.

## Features

- Username/password auth (register + login, no email confirmation).
- Start a workout from a template (Upper A, Upper B, Lower A, Lower B).
- Add extra exercises from two configurable pools (Exercise Pool, Functional).
- Auto-save: every change to sets, reps, weight, or completion is saved instantly.
- Weight and reps are remembered per exercise name and pre-filled on the next workout.
- Complete history log of past workouts with full exercise detail.
- Progression analytics: estimated 1RM, weight progression, volume, workout frequency, template breakdown, and personal records.
- Timed exercises (e.g. Farmer's Walks, Plate Pinch Holds) log seconds instead of reps.
- Templates and pools are fully configurable via a JSON file.

## Requirements

- Python 3.10+ (the `sqlite3` standard-library module must be available)
- Flask 3.x

## Setup

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt
```

> If your default Python is missing the `_sqlite3` module (common with `pyenv` builds),
> create the venv with a Python that has it, e.g. `/usr/bin/python3.10 -m venv .venv`.

## Run

```bash
python app.py
```

Then open http://127.0.0.1:5000 and create an account.

The server binds to `127.0.0.1` on the port from the `PORT` environment variable (default `5000`):

```bash
PORT=8000 python app.py
```

To run in development mode with auto-reload, set `debug=True` in `app.py` (it is on by default).

## Run in production (Gunicorn)

[`gunicorn.conf.py`](gunicorn.conf.py) runs the app as a background daemon bound to `0.0.0.0:8085`, with logs and a PID file under `var/`.

```bash
# start (runs in the background)
gunicorn -c gunicorn.conf.py app:app

# check it's up
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8085/login

# stop
kill $(cat var/run/dimi-ul.pid)
```

Logs are written to `var/log/dimi-ul.log`; the PID file is `var/run/dimi-ul.pid` (both directories are created automatically and are gitignored).

The config uses a single `gthread` worker with 4 threads — right for Flask + SQLite, since a single process avoids "database is locked" errors. `reload` is off for production.

## Demo user

On first startup the app seeds a demo account so you can explore it with data:

- Username: `test`
- Password: `test`

It includes five completed workouts spread over the past month (so the Log and Progress pages have data) plus one in-progress, half-finished "Upper A" workout. Seeding is idempotent: it only runs if the `test` user has no workouts yet, and it never touches other users.

To disable the demo user, run:

```bash
SEED_DEMO=0 python app.py
```

## Configuration

All templates and exercise pools live in [`config/templates.json`](config/templates.json).
The config is read once when the server starts, so **restart the server after editing the file**.

Structure overview:

- `templates` — the workout presets. Each has an `id`, `name`, `color`, `emoji`, and an `exercises` list.
- `pools` — additional exercise banks the user can add on top of a template.
- Each exercise has:
  - `block` — superset group label (e.g. `"A1"`, `"B"`). Optional for pool exercises.
  - `name` — display name. Weight/reps memory is keyed on this, so keep it consistent across templates to share history.
  - `sets_reps` — reference hint shown on the exercise card (e.g. `"3 x 8-12"`).
  - `notes` — coaching note shown under the name. Optional.
  - `metric` — `"reps"` for normal exercises or `"seconds"` for timed ones.

### Editing a template exercise

Each template exercise looks like this:

```json
{ "block": "A1", "name": "Incline Dumbbell Press", "sets_reps": "3 x 8-12",
  "notes": "Superset with A2. Rest 60s after A2.", "metric": "reps" }
```

- **Rename** — change `name` (note: existing history is kept under the old name; a renamed exercise starts fresh).
- **Change the target range** — edit `sets_reps` (the app still defaults sets to 3 and reps to 8; this is just a hint).
- **Change the note** — edit `notes`, or set it to `""` to hide it.
- **Remove it** — delete the whole `{ ... }` entry (make sure the JSON stays valid).
- **Add one** — insert a new `{ ... }` entry in the position you want it to appear.
- **Make it timed** — set `"metric": "seconds"` (logs seconds instead of reps, e.g. Farmer's Walks).

### Editing a pool exercise

Pool exercises are simpler — just `name` and `metric`:

```json
{ "name": "Deficit Reverse Lunges", "metric": "reps" }
```

Add or remove entries in the `exercises` array of `exercise_pool` or `functional` the same way.

### Adding a new template or pool

Copy an existing entry and change the `id`, `name`, `color`, and `emoji`. Template `id`s must be unique; `color` is any CSS color (used as the card accent). New templates and pools are picked up automatically on restart.

### Notes

- The app stores a snapshot of each finished workout's exercises, so editing the config later does not rewrite past history.
- Weight and reps memory is per user, per exact exercise `name`.

## Defaults

- Sets default to 3 (editable in a session, but always reset to 3 next time).
- Reps default to 8 and are remembered per exercise.
- Weight starts empty until you enter a value, then is remembered per exercise.
- Timed exercises default to 30 seconds and are remembered the same way.

## Data

- `dimi_ul.db` — SQLite database (created automatically on first run).
- `.secret_key` — auto-generated session signing key (created automatically).

Both files are gitignored.
