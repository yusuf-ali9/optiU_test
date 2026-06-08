# StreakBoard

A personal consistency dashboard that tracks whether you followed through on your daily goal, deep work, and habits — and shows you the streaks to prove it.

**The real problem it solves:** It's easy to feel productive day-to-day but lose track of whether you're actually consistent over time; StreakBoard gives you a single honest view of your follow-through.

---

## What it does

- Track a **Main Daily Goal**, **Deep Work**, and any custom **Habits** you add
- Check off each item daily with an optional note
- See your **current streak** and **best streak** for each item
- View the last **7 days** at a glance (green ✓ = done, red ✗ = missed)
- A **weekly summary** table shows completion across all trackables
- Data persists in a local SQLite database — survives restarts

---

## Setup

### 1. Create and activate a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the app

```bash
uvicorn main:app --reload
```

Then open your browser at **http://localhost:8000**

---

## Stack

| Layer      | Technology                     |
|------------|-------------------------------|
| Backend    | FastAPI (Python)               |
| Database   | SQLite (via Python's sqlite3)  |
| Frontend   | Plain HTML + CSS + JavaScript  |
| Server     | Uvicorn (ASGI)                 |

---

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Dashboard UI |
| GET | `/api/dashboard` | All trackables with streaks & check-ins |
| POST | `/api/trackables` | Create a new habit |
| PUT | `/api/trackables/{id}` | Update a trackable |
| DELETE | `/api/trackables/{id}` | Remove a habit (soft delete) |
| POST | `/api/checkins` | Create or update today's check-in |
| PUT | `/api/checkins/{id}` | Update an existing check-in |
