import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("swimming_bot.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id           INTEGER PRIMARY KEY,
            level             TEXT,
            goal              TEXT,
            pool_length       TEXT,
            duration          TEXT,
            sessions_per_week TEXT,
            strokes           TEXT,
            injuries          TEXT,
            updated_at        TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS workouts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER NOT NULL,
            workout_text     TEXT NOT NULL,
            completed        INTEGER DEFAULT 0,
            perceived_effort INTEGER,
            feedback         TEXT,
            distance_meters  INTEGER,
            created_at       TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_workouts_user_date
        ON workouts(user_id, created_at)
    """)
    conn.commit()
    conn.close()
    _migrate_db()


def _add_column(c, table: str, column: str, col_type: str):
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


def _migrate_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    for col, col_type in [
        ("experience", "TEXT"),
        ("best_100m_time", "TEXT"),
        ("reminder_days", "TEXT DEFAULT '[]'"),
        ("reminders_enabled", "INTEGER DEFAULT 0"),
        ("created_at", "TEXT"),
        ("last_reminder_sent", "TEXT"),
    ]:
        _add_column(c, "users", col, col_type)

    for col, col_type in [
        ("workout_type", "TEXT"),
        ("completion_rate", "TEXT DEFAULT 'full'"),
        ("actual_distance", "INTEGER"),
        ("saved", "INTEGER DEFAULT 0"),
    ]:
        _add_column(c, "workouts", col, col_type)

    conn.commit()
    conn.close()


def save_user_profile(user_id: int, user_data: dict):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO users
            (user_id, level, goal, pool_length, duration, sessions_per_week, strokes, injuries, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            level=excluded.level,
            goal=excluded.goal,
            pool_length=excluded.pool_length,
            duration=excluded.duration,
            sessions_per_week=excluded.sessions_per_week,
            strokes=excluded.strokes,
            injuries=excluded.injuries,
            updated_at=excluded.updated_at
    """, (
        user_id,
        user_data.get("level"),
        user_data.get("goal"),
        user_data.get("pool_length"),
        user_data.get("duration"),
        user_data.get("sessions_per_week"),
        json.dumps(user_data.get("strokes", [])),
        user_data.get("injuries"),
        datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def get_user_profile(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT level, goal, pool_length, duration, sessions_per_week, strokes, injuries,
                  experience, best_100m_time, reminder_days, reminders_enabled, last_reminder_sent
           FROM users WHERE user_id = ?""",
        (user_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "level": row[0],
        "goal": row[1],
        "pool_length": row[2],
        "duration": row[3],
        "sessions_per_week": row[4],
        "strokes": json.loads(row[5]) if row[5] else ["freestyle"],
        "injuries": row[6],
        "experience": row[7],
        "best_100m_time": row[8],
        "reminder_days": row[9] or "[]",
        "reminders_enabled": row[10] or 0,
        "last_reminder_sent": row[11],
    }


def update_reminder_sent(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET last_reminder_sent = ? WHERE user_id = ?",
        (datetime.now().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def update_user_field(user_id: int, field: str, value) -> None:
    allowed = {
        "level", "goal", "pool_length", "duration", "sessions_per_week",
        "strokes", "injuries", "experience", "best_100m_time",
        "reminder_days", "reminders_enabled",
    }
    if field not in allowed:
        raise ValueError(f"Поле {field} не разрешено")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def save_workout(user_id: int, workout_text: str, workout_type: str = None, distance_meters: int = None) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")
    c.execute(
        "DELETE FROM workouts WHERE user_id = ? AND date(created_at) = ?",
        (user_id, today),
    )

    c.execute(
        "INSERT INTO workouts (user_id, workout_text, workout_type, distance_meters, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, workout_text, workout_type, distance_meters, datetime.now().isoformat()),
    )
    workout_id = c.lastrowid

    c.execute(
        """DELETE FROM workouts WHERE user_id = ? AND id NOT IN (
            SELECT id FROM workouts WHERE user_id = ? ORDER BY created_at DESC LIMIT 10
        )""",
        (user_id, user_id),
    )

    conn.commit()
    conn.close()
    return workout_id


def get_workout_by_id(workout_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, workout_text, distance_meters, workout_type, created_at FROM workouts WHERE id = ?",
        (workout_id,),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "workout_text": row[1],
        "distance_meters": row[2],
        "workout_type": row[3] or "выносливость",
        "date": row[4][:10] if row[4] else "—",
    }


def mark_workout_saved(workout_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE workouts SET saved = 1 WHERE id = ?", (workout_id,))
    conn.commit()
    conn.close()


def get_saved_workouts(user_id: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT id, workout_type, distance_meters, created_at
           FROM workouts WHERE user_id = ? AND saved = 1
           ORDER BY created_at DESC LIMIT 20""",
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "workout_type": row[1] or "выносливость",
            "distance_meters": row[2],
            "date": row[3][:10] if row[3] else "—",
        }
        for row in rows
    ]


def mark_workout_completed(
    workout_id: int,
    perceived_effort: int,
    feedback: str,
    distance_meters,
    completion_rate: str = "full",
    actual_distance: int = None,
):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """UPDATE workouts
           SET completed=1, perceived_effort=?, feedback=?, distance_meters=?,
               completion_rate=?, actual_distance=?
           WHERE id=?""",
        (perceived_effort, feedback, distance_meters, completion_rate, actual_distance, workout_id),
    )
    conn.commit()
    conn.close()


def get_workout_history(user_id: int, limit: int = 20) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT id, workout_text, completed, perceived_effort, feedback, distance_meters, created_at, workout_type
           FROM workouts WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "workout_text": row[1],
            "completed": bool(row[2]),
            "perceived_effort": row[3],
            "feedback": row[4],
            "distance_meters": row[5],
            "date": row[6][:10] if row[6] else "—",
            "workout_type": row[7] or "выносливость",
        }
        for row in rows
    ]


def get_stats(user_id: int) -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        "SELECT COUNT(*), SUM(distance_meters), AVG(perceived_effort) "
        "FROM workouts WHERE user_id = ? AND completed = 1",
        (user_id,),
    )
    row = c.fetchone()
    total_workouts = row[0] or 0
    total_distance = int(row[1] or 0)
    avg_effort_all = round(row[2] or 0, 1)

    thirty_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    c.execute(
        "SELECT COUNT(*), SUM(distance_meters), AVG(perceived_effort) "
        "FROM workouts WHERE user_id = ? AND completed = 1 AND date(created_at) >= ?",
        (user_id, thirty_ago),
    )
    row30 = c.fetchone()
    workouts_30d = row30[0] or 0
    distance_30d = int(row30[1] or 0)
    avg_effort_30d = round(row30[2] or 0, 1)

    sixty_ago = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    c.execute(
        "SELECT SUM(distance_meters) FROM workouts "
        "WHERE user_id = ? AND completed = 1 AND date(created_at) >= ? AND date(created_at) < ?",
        (user_id, sixty_ago, thirty_ago),
    )
    prev_distance_30d = int(c.fetchone()[0] or 0)

    c.execute(
        "SELECT COUNT(*) FROM workouts WHERE user_id = ? AND completed = 1 AND completion_rate = 'partial'",
        (user_id,),
    )
    partial_count = c.fetchone()[0] or 0

    c.execute(
        "SELECT MAX(distance_meters) FROM workouts WHERE user_id = ? AND completed = 1",
        (user_id,),
    )
    best_distance = c.fetchone()[0] or 0

    c.execute(
        "SELECT perceived_effort FROM workouts WHERE user_id = ? AND completed = 1 "
        "ORDER BY created_at DESC LIMIT 5",
        (user_id,),
    )
    recent_efforts = [r[0] for r in c.fetchall() if r[0]]

    c.execute(
        "SELECT distance_meters, workout_type FROM workouts WHERE user_id = ? AND completed = 1 "
        "ORDER BY created_at DESC LIMIT 8",
        (user_id,),
    )
    last_8 = [(r[0], r[1] or "выносливость") for r in c.fetchall()]

    c.execute(
        "SELECT DISTINCT date(created_at) FROM workouts "
        "WHERE user_id = ? AND completed = 1 ORDER BY date(created_at) DESC",
        (user_id,),
    )
    dates = [r[0] for r in c.fetchall()]
    conn.close()

    streak = 0
    today = datetime.now().date()
    for i, d_str in enumerate(dates):
        if datetime.strptime(d_str, "%Y-%m-%d").date() == today - timedelta(days=i):
            streak += 1
        else:
            break

    effort_trend = ""
    if len(recent_efforts) >= 2:
        if recent_efforts[0] > recent_efforts[-1]:
            effort_trend = "↑ растёт"
        elif recent_efforts[0] < recent_efforts[-1]:
            effort_trend = "↓ снижается"
        else:
            effort_trend = "→ стабильна"

    return {
        "total_workouts": total_workouts,
        "total_distance": total_distance,
        "avg_effort_all": avg_effort_all,
        "workouts_30d": workouts_30d,
        "distance_30d": distance_30d,
        "avg_effort_30d": avg_effort_30d,
        "prev_distance_30d": prev_distance_30d,
        "partial_count": partial_count,
        "best_distance": best_distance,
        "streak": streak,
        "effort_trend": effort_trend,
        "last_8": last_8,
    }


def get_week_workouts(user_id: int) -> list:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT id, workout_type, completed, perceived_effort, distance_meters, created_at
           FROM workouts
           WHERE user_id = ? AND date(created_at) >= ? AND date(created_at) <= ?
           ORDER BY created_at ASC""",
        (user_id, monday.isoformat(), sunday.isoformat()),
    )
    rows = c.fetchall()
    conn.close()

    result = []
    for row in rows:
        date_str = row[5][:10] if row[5] else None
        weekday = 0
        if date_str:
            try:
                weekday = datetime.strptime(date_str, "%Y-%m-%d").weekday()
            except ValueError:
                pass
        result.append({
            "id": row[0],
            "workout_type": row[1] or "выносливость",
            "completed": bool(row[2]),
            "perceived_effort": row[3],
            "distance_meters": row[4],
            "date": date_str or "—",
            "weekday": weekday,
        })
    return result


def get_users_for_reminder() -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE reminders_enabled = 1")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]
