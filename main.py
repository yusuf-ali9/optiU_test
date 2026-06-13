import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

DB_PATH = Path(__file__).parent / "streakboard.db"

app = FastAPI(title="StreakBoard")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

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


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS sections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS trackables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                section_id INTEGER REFERENCES sections(id),
                interval TEXT NOT NULL DEFAULT 'daily',
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
        # Migrate old schema: add columns if missing
        for stmt in [
            "ALTER TABLE trackables ADD COLUMN section_id INTEGER REFERENCES sections(id)",
            "ALTER TABLE trackables ADD COLUMN interval TEXT NOT NULL DEFAULT 'daily'",
        ]:
            try:
                db.execute(stmt)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Streak / history helpers
# ---------------------------------------------------------------------------

def calculate_streaks(checkins_rows, interval: str, today: str):
    completed_dates = {c["date"] for c in checkins_rows if c["completed"]}
    if not completed_dates:
        return 0, 0

    today_d = date.fromisoformat(today)

    if interval == "weekly":
        # Week starts on Monday
        week_start = today_d - timedelta(days=today_d.weekday())

        def week_has_completion(ws: date) -> bool:
            return any(
                (ws + timedelta(days=d)).isoformat() in completed_dates
                for d in range(7)
            )

        # Current streak: this week counts if done; else fall back to last week
        start_offset = 0 if week_has_completion(week_start) else 1
        current = 0
        for wb in range(start_offset, 54):
            ws = week_start - timedelta(weeks=wb)
            if week_has_completion(ws):
                current += 1
            else:
                break

        # Best streak across all weeks
        if completed_dates:
            oldest = date.fromisoformat(min(completed_dates))
            oldest_ws = oldest - timedelta(days=oldest.weekday())
            best = 0
            run = 0
            ws = oldest_ws
            while ws <= week_start:
                if week_has_completion(ws):
                    run += 1
                    best = max(best, run)
                else:
                    run = 0
                ws += timedelta(weeks=1)
        else:
            best = 0

        return current, best

    # Daily streak
    yesterday_d = today_d - timedelta(days=1)
    if today in completed_dates:
        d = today_d
    elif yesterday_d.isoformat() in completed_dates:
        d = yesterday_d
    else:
        d = None

    current = 0
    if d:
        while d.isoformat() in completed_dates:
            current += 1
            d -= timedelta(days=1)

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


def get_last_7_days(checkins_rows, today: str):
    today_d = date.fromisoformat(today)
    completed = {c["date"] for c in checkins_rows if c["completed"]}
    checked_in = {c["date"] for c in checkins_rows}
    result = []
    for i in range(6, -1, -1):
        d = (today_d - timedelta(days=i)).isoformat()
        if d in completed:
            result.append("completed")
        elif d == today and d not in checked_in:
            result.append("pending")
        else:
            result.append("missed")
    return result


def build_trackable_data(row, checkins_rows, today: str):
    interval = row["interval"] or "daily"
    current_streak, best_streak = calculate_streaks(checkins_rows, interval, today)
    last_7 = get_last_7_days(checkins_rows, today)

    checkin_map = {c["date"]: c for c in checkins_rows}
    today_row = checkin_map.get(today)

    return {
        "id": row["id"],
        "name": row["name"],
        "section_id": row["section_id"],
        "interval": interval,
        "target_description": row["target_description"],
        "current_streak": current_streak,
        "best_streak": best_streak,
        "last_7_days": last_7,
        "today_checkin": {
            "id": today_row["id"] if today_row else None,
            "completed": bool(today_row["completed"]) if today_row else False,
            "notes": today_row["notes"] if today_row else "",
        },
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SectionCreate(BaseModel):
    name: str

class SectionUpdate(BaseModel):
    name: Optional[str] = None

class TrackableCreate(BaseModel):
    name: str
    section_id: Optional[int] = None
    interval: str = "daily"
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

class ChatMessage(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Routes — General
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse("templates/index.html")


# ---------------------------------------------------------------------------
# Routes — Sections
# ---------------------------------------------------------------------------

@app.get("/api/sections")
def get_sections():
    with get_db() as db:
        rows = db.execute("SELECT * FROM sections ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


@app.post("/api/sections", status_code=201)
def create_section(body: SectionCreate):
    with get_db() as db:
        cur = db.execute("INSERT INTO sections (name) VALUES (?)", (body.name.strip(),))
        row = db.execute("SELECT * FROM sections WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put("/api/sections/{section_id}")
def update_section(section_id: int, body: SectionUpdate):
    with get_db() as db:
        row = db.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Section not found")
        name = body.name.strip() if body.name else row["name"]
        db.execute("UPDATE sections SET name = ? WHERE id = ?", (name, section_id))
        updated = db.execute("SELECT * FROM sections WHERE id = ?", (section_id,)).fetchone()
    return dict(updated)


@app.delete("/api/sections/{section_id}", status_code=204)
def delete_section(section_id: int):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM sections WHERE id = ?", (section_id,)).fetchone():
            raise HTTPException(404, "Section not found")
        db.execute("UPDATE trackables SET active = 0 WHERE section_id = ?", (section_id,))
        db.execute("DELETE FROM sections WHERE id = ?", (section_id,))


# ---------------------------------------------------------------------------
# Routes — Trackables
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def dashboard():
    today = date.today().isoformat()
    with get_db() as db:
        sections = db.execute("SELECT * FROM sections ORDER BY created_at").fetchall()
        trackables = db.execute(
            "SELECT * FROM trackables WHERE active = 1 ORDER BY created_at"
        ).fetchall()

        result = []
        for t in trackables:
            checkins = db.execute(
                "SELECT * FROM checkins WHERE trackable_id = ? ORDER BY date",
                (t["id"],),
            ).fetchall()
            result.append(build_trackable_data(t, checkins, today))

    return {
        "today": today,
        "sections": [dict(s) for s in sections],
        "trackables": result,
    }


@app.post("/api/trackables", status_code=201)
def create_trackable(body: TrackableCreate):
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO trackables (name, section_id, interval, target_description) VALUES (?, ?, ?, ?)",
            (body.name.strip(), body.section_id, body.interval, body.target_description),
        )
        row = db.execute("SELECT * FROM trackables WHERE id = ?", (cur.lastrowid,)).fetchone()
        checkins = []
    return build_trackable_data(row, checkins, date.today().isoformat())


@app.put("/api/trackables/{trackable_id}")
def update_trackable(trackable_id: int, body: TrackableUpdate):
    with get_db() as db:
        row = db.execute("SELECT * FROM trackables WHERE id = ?", (trackable_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        name = body.name.strip() if body.name is not None else row["name"]
        active = int(body.active) if body.active is not None else row["active"]
        desc = body.target_description if body.target_description is not None else row["target_description"]
        db.execute(
            "UPDATE trackables SET name = ?, active = ?, target_description = ? WHERE id = ?",
            (name, active, desc, trackable_id),
        )
        updated = db.execute("SELECT * FROM trackables WHERE id = ?", (trackable_id,)).fetchone()
        checkins = db.execute(
            "SELECT * FROM checkins WHERE trackable_id = ? ORDER BY date", (trackable_id,)
        ).fetchall()
    return build_trackable_data(updated, checkins, date.today().isoformat())


@app.delete("/api/trackables/{trackable_id}", status_code=204)
def delete_trackable(trackable_id: int):
    with get_db() as db:
        if not db.execute("SELECT 1 FROM trackables WHERE id = ?", (trackable_id,)).fetchone():
            raise HTTPException(404, "Not found")
        db.execute("UPDATE trackables SET active = 0 WHERE id = ?", (trackable_id,))


# ---------------------------------------------------------------------------
# Routes — Check-ins
# ---------------------------------------------------------------------------

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
            raise HTTPException(404, "Not found")
        completed = int(body.completed) if body.completed is not None else row["completed"]
        notes = body.notes if body.notes is not None else row["notes"]
        db.execute(
            "UPDATE checkins SET completed = ?, notes = ? WHERE id = ?",
            (completed, notes, checkin_id),
        )
        updated = db.execute("SELECT * FROM checkins WHERE id = ?", (checkin_id,)).fetchone()
    return dict(updated)


# ---------------------------------------------------------------------------
# Routes — Analytics
# ---------------------------------------------------------------------------

@app.get("/api/analytics/monthly")
def monthly_analytics():
    today = date.today()
    month_start = today.replace(day=1)

    with get_db() as db:
        trackables = db.execute(
            "SELECT id, name FROM trackables WHERE active = 1 ORDER BY created_at"
        ).fetchall()

        weeks = []
        for w in range(4):
            ws = month_start + timedelta(weeks=w)
            we = ws + timedelta(days=6)
            weeks.append({"label": f"Week {w + 1}", "start": ws.isoformat(), "end": we.isoformat()})

        habits = []
        for t in trackables:
            counts = []
            for wk in weeks:
                n = db.execute(
                    """SELECT COUNT(*) FROM checkins
                       WHERE trackable_id = ? AND date >= ? AND date <= ? AND completed = 1""",
                    (t["id"], wk["start"], wk["end"]),
                ).fetchone()[0]
                counts.append(n)
            habits.append({"id": t["id"], "name": t["name"], "counts": counts})

    return {"labels": [w["label"] for w in weeks], "habits": habits}


@app.get("/api/analytics/sixmonth")
def sixmonth_analytics():
    today = date.today()

    months = []
    for m in range(5, -1, -1):
        month_num = today.month - m
        year = today.year
        while month_num <= 0:
            month_num += 12
            year -= 1
        start = date(year, month_num, 1)
        if month_num == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month_num + 1, 1)
        months.append({
            "label": start.strftime("%b %Y"),
            "start": start.isoformat(),
            "end": end.isoformat(),
        })

    with get_db() as db:
        trackables = db.execute(
            "SELECT id, name FROM trackables WHERE active = 1 ORDER BY created_at"
        ).fetchall()

        habits = []
        for t in trackables:
            counts = []
            for mo in months:
                n = db.execute(
                    """SELECT COUNT(*) FROM checkins
                       WHERE trackable_id = ? AND date >= ? AND date < ? AND completed = 1""",
                    (t["id"], mo["start"], mo["end"]),
                ).fetchone()[0]
                counts.append(n)
            habits.append({"id": t["id"], "name": t["name"], "counts": counts})

    return {"labels": [mo["label"] for mo in months], "habits": habits}


# ---------------------------------------------------------------------------
# Routes — Chatbot
# ---------------------------------------------------------------------------

@app.post("/api/chat")
def chat(body: ChatMessage):
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise HTTPException(500, "GROQ_API_KEY is not configured")

    today = date.today().isoformat()
    with get_db() as db:
        sections = db.execute("SELECT * FROM sections").fetchall()
        trackables = db.execute("SELECT * FROM trackables WHERE active = 1").fetchall()

        context_lines = [f"Today is {today}."]
        section_names = ", ".join(s["name"] for s in sections) or "none"
        context_lines.append(f"Sections: {section_names}.")

        for t in trackables:
            checkins = db.execute(
                "SELECT * FROM checkins WHERE trackable_id = ? ORDER BY date", (t["id"],)
            ).fetchall()
            interval = t["interval"] or "daily"
            current, best = calculate_streaks(checkins, interval, today)
            last_7 = get_last_7_days(checkins, today)
            done_this_week = sum(1 for s in last_7 if s == "completed")
            context_lines.append(
                f"Habit '{t['name']}' (interval={interval}): "
                f"current streak={current}, best streak={best}, "
                f"completed {done_this_week}/7 days this week."
            )

    system_prompt = (
        "You are StreakBot, a helpful assistant built into the StreakBoard habit tracker. "
        "Answer questions about the user's habits, streaks, and progress using the data below. "
        "Be concise, warm, and encouraging. If asked something unrelated to habits, "
        "politely redirect.\n\nCurrent habit data:\n" + "\n".join(context_lines)
    )

    from groq import Groq
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": body.message},
        ],
        max_tokens=512,
    )
    return {"reply": completion.choices[0].message.content}


# ---------------------------------------------------------------------------
# Routes — Clear all data
# ---------------------------------------------------------------------------

@app.delete("/api/clear", status_code=204)
def clear_all():
    with get_db() as db:
        db.execute("DELETE FROM checkins")
        db.execute("DELETE FROM trackables")
        db.execute("DELETE FROM sections")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    init_db()
