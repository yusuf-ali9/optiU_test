import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

DB_PATH = Path("streakboard.db")

app = FastAPI(title="StreakBoard")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS trackables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                target_description TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trackable_id INTEGER NOT NULL REFERENCES trackables(id),
                date TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                UNIQUE(trackable_id, date)
            );
        """)
        # Seed default trackables
        for name, kind in [("Main Daily Goal", "daily_goal"), ("Deep Work", "deep_work")]:
            db.execute(
                "INSERT OR IGNORE INTO trackables (name, type) SELECT ?, ? "
                "WHERE NOT EXISTS (SELECT 1 FROM trackables WHERE name = ? AND type = ?)",
                (name, kind, name, kind),
            )


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Streak / history helpers
# ---------------------------------------------------------------------------

def calculate_streaks(completed_dates: set, today: str):
    if not completed_dates:
        return 0, 0

    today_d = date.fromisoformat(today)
    yesterday_d = today_d - timedelta(days=1)

    # Current streak
    current = 0
    if today in completed_dates:
        d = today_d
    elif yesterday_d.isoformat() in completed_dates:
        d = yesterday_d
    else:
        d = None

    if d:
        while d.isoformat() in completed_dates:
            current += 1
            d -= timedelta(days=1)

    # Best streak
    sorted_dates = sorted(completed_dates)
    best = 1 if sorted_dates else 0
    run = 1
    for i in range(1, len(sorted_dates)):
        d1 = date.fromisoformat(sorted_dates[i - 1])
        d2 = date.fromisoformat(sorted_dates[i])
        if (d2 - d1).days == 1:
            run += 1
            best = max(best, run)
        else:
            run = 1

    return current, best


def get_last_7_days(completed_dates: set, today: str, checkin_map: dict):
    today_d = date.fromisoformat(today)
    result = []
    for i in range(6, -1, -1):
        d = (today_d - timedelta(days=i)).isoformat()
        if d in completed_dates:
            result.append({"date": d, "status": "completed"})
        elif d == today and d not in checkin_map:
            result.append({"date": d, "status": "today_pending"})
        else:
            result.append({"date": d, "status": "missed"})
    return result


def build_trackable_data(row, checkins_rows, today: str):
    completed_dates = {c["date"] for c in checkins_rows if c["completed"]}
    checkin_map = {c["date"]: c for c in checkins_rows}

    current_streak, best_streak = calculate_streaks(completed_dates, today)
    last_7 = get_last_7_days(completed_dates, today, checkin_map)

    today_row = checkin_map.get(today)
    today_checkin = {
        "id": today_row["id"] if today_row else None,
        "completed": bool(today_row["completed"]) if today_row else False,
        "notes": today_row["notes"] if today_row else "",
    }

    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "target_description": row["target_description"],
        "current_streak": current_streak,
        "best_streak": best_streak,
        "last_7_days": last_7,
        "today_checkin": today_checkin,
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TrackableCreate(BaseModel):
    name: str
    type: str = "habit"
    target_description: Optional[str] = None


class TrackableUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None
    target_description: Optional[str] = None


class CheckInUpsert(BaseModel):
    trackable_id: int
    date: str
    completed: bool
    notes: Optional[str] = ""


class CheckInUpdate(BaseModel):
    completed: Optional[bool] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse("templates/index.html")


@app.get("/api/dashboard")
def dashboard():
    today = date.today().isoformat()

    with get_db() as db:
        trackables = db.execute(
            "SELECT * FROM trackables WHERE active = 1 ORDER BY id"
        ).fetchall()

        result = []
        total_completed = 0
        today_d = date.fromisoformat(today)

        for t in trackables:
            checkins = db.execute(
                "SELECT * FROM checkins WHERE trackable_id = ? ORDER BY date",
                (t["id"],),
            ).fetchall()

            # Count completed check-ins in last 7 days for weekly summary
            for c in checkins:
                c_date = date.fromisoformat(c["date"])
                if c["completed"] and (today_d - timedelta(days=6)) <= c_date <= today_d:
                    total_completed += 1

            result.append(build_trackable_data(t, checkins, today))

        total_possible = len(trackables) * 7
        completion_pct = round(total_completed / total_possible * 100, 1) if total_possible else 0

    return {
        "today": today,
        "trackables": result,
        "weekly_summary": {
            "total_completed": total_completed,
            "total_possible": total_possible,
            "completion_pct": completion_pct,
        },
    }


@app.post("/api/trackables", status_code=201)
def create_trackable(body: TrackableCreate):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO trackables (name, type, target_description) VALUES (?, ?, ?)",
            (body.name.strip(), body.type, body.target_description),
        )
        row = db.execute("SELECT * FROM trackables WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/trackables/{trackable_id}")
def update_trackable(trackable_id: int, body: TrackableUpdate):
    with get_db() as db:
        row = db.execute("SELECT * FROM trackables WHERE id = ?", (trackable_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        name = body.name.strip() if body.name is not None else row["name"]
        active = int(body.active) if body.active is not None else row["active"]
        desc = body.target_description if body.target_description is not None else row["target_description"]
        db.execute(
            "UPDATE trackables SET name = ?, active = ?, target_description = ? WHERE id = ?",
            (name, active, desc, trackable_id),
        )
        updated = db.execute("SELECT * FROM trackables WHERE id = ?", (trackable_id,)).fetchone()
    return dict(updated)


@app.delete("/api/trackables/{trackable_id}", status_code=204)
def delete_trackable(trackable_id: int):
    with get_db() as db:
        row = db.execute("SELECT * FROM trackables WHERE id = ?", (trackable_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        db.execute("UPDATE trackables SET active = 0 WHERE id = ?", (trackable_id,))


@app.post("/api/checkins", status_code=201)
def upsert_checkin(body: CheckInUpsert):
    with get_db() as db:
        db.execute(
            """INSERT INTO checkins (trackable_id, date, completed, notes)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(trackable_id, date) DO UPDATE SET
                   completed = excluded.completed,
                   notes = excluded.notes""",
            (body.trackable_id, body.date, int(body.completed), body.notes or ""),
        )
        row = db.execute(
            "SELECT * FROM checkins WHERE trackable_id = ? AND date = ?",
            (body.trackable_id, body.date),
        ).fetchone()
    return dict(row)


@app.put("/api/checkins/{checkin_id}")
def update_checkin(checkin_id: int, body: CheckInUpdate):
    with get_db() as db:
        row = db.execute("SELECT * FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        completed = int(body.completed) if body.completed is not None else row["completed"]
        notes = body.notes if body.notes is not None else row["notes"]
        db.execute(
            "UPDATE checkins SET completed = ?, notes = ? WHERE id = ?",
            (completed, notes, checkin_id),
        )
        updated = db.execute("SELECT * FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
    return dict(updated)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()
