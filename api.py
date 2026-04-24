import asyncio
import hashlib
import hmac
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, unquote

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import (
    init_db,
    get_stats,
    get_user_profile,
    get_workout_by_id,
    get_workout_history,
    get_week_workouts,
    mark_workout_completed,
    mark_workout_saved,
    get_saved_workouts,
    save_user_profile,
    save_workout,
    update_user_field,
)
from workout_generator import (
    generate_workout, extract_distance, extract_workout_type,
    adjust_workout, ask_workout_question,
)

app = FastAPI(title="SwimBot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_WEBAPP_DIR = Path(__file__).parent / "webapp"
_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


@app.on_event("startup")
async def _startup():
    init_db()


def _validate_init_data(init_data: str) -> int:
    params = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = params.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Нет hash в initData")

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", _BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise HTTPException(status_code=401, detail="Неверная подпись initData")

    user_data = json.loads(unquote(params.get("user", "{}")))
    user_id = user_data.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Нет user.id в initData")
    return int(user_id)


def get_current_user(x_telegram_init_data: str = Header(...)) -> int:
    return _validate_init_data(x_telegram_init_data)


@app.get("/")
async def root():
    path = _WEBAPP_DIR / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="webapp/index.html не найден")
    return FileResponse(path)


# ── Models ────────────────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    field: str
    value: str


class ProfileSetup(BaseModel):
    level: str
    goal: str
    pool_length: str
    duration: str
    sessions_per_week: str
    usual_distance: str | None = None
    strokes: list[str] = []
    injuries: str = ""
    training_days: list[str] = []


class WorkoutLog(BaseModel):
    workout_id: int
    perceived_effort: int
    feedback: str = ""
    distance_meters: int = None
    completion_rate: str = "full"
    actual_distance: int = None


class WorkoutSave(BaseModel):
    workout_id: int


class WorkoutAdjust(BaseModel):
    workout_id: int
    direction: str  # "harder" | "easier"


class WorkoutQuestion(BaseModel):
    workout_id: int
    question: str


# ── Profile ───────────────────────────────────────────────────────────────────

@app.get("/api/profile")
async def api_profile(user_id: int = Depends(get_current_user)):
    profile = get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    return profile


@app.post("/api/profile")
async def api_update_profile(data: ProfileUpdate, user_id: int = Depends(get_current_user)):
    try:
        update_user_field(user_id, data.field, data.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/api/profile/setup")
async def api_profile_setup(data: ProfileSetup, user_id: int = Depends(get_current_user)):
    save_user_profile(user_id, data.dict())
    return {"ok": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats(user_id: int = Depends(get_current_user)):
    return get_stats(user_id)


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/api/history")
async def api_history(user_id: int = Depends(get_current_user)):
    history = get_workout_history(user_id, limit=20)
    for w in history:
        w.pop("workout_text", None)
    return history


@app.get("/api/history/saved")
async def api_history_saved(user_id: int = Depends(get_current_user)):
    saved = get_saved_workouts(user_id)
    for w in saved:
        w.pop("workout_text", None)
    return saved


# ── Week ──────────────────────────────────────────────────────────────────────

@app.get("/api/week")
async def api_week(user_id: int = Depends(get_current_user)):
    return get_week_workouts(user_id)


# ── Workouts ──────────────────────────────────────────────────────────────────

@app.get("/api/workout/today")
async def api_workout_today(user_id: int = Depends(get_current_user)):
    history = get_workout_history(user_id, limit=5)
    today = str(date.today())
    for w in history:
        if w.get("date") == today:
            return get_workout_by_id(w["id"])
    return None


@app.get("/api/workout/{workout_id}")
async def api_workout(workout_id: int, user_id: int = Depends(get_current_user)):
    w = get_workout_by_id(workout_id)
    if not w:
        raise HTTPException(status_code=404, detail="Тренировка не найдена")
    return w


@app.post("/api/workout/generate")
async def api_generate_workout(user_id: int = Depends(get_current_user)):
    profile = get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    history = get_workout_history(user_id, limit=10)
    loop = asyncio.get_event_loop()
    workout_text, explanation, used_exercises = await loop.run_in_executor(
        None, generate_workout, profile, history
    )
    workout_type = extract_workout_type(workout_text)
    distance = extract_distance(workout_text)
    workout_id = save_workout(user_id, workout_text, workout_type, distance, used_exercises)
    return {
        "id": workout_id,
        "workout_text": workout_text,
        "workout_type": workout_type,
        "distance_meters": distance,
        "explanation": explanation,
        "completed": False,
        "date": str(date.today()),
    }


@app.post("/api/workout/save")
async def api_save_workout(data: WorkoutSave, user_id: int = Depends(get_current_user)):
    mark_workout_saved(data.workout_id)
    return {"ok": True}


@app.post("/api/workout/adjust")
async def api_adjust_workout(data: WorkoutAdjust, user_id: int = Depends(get_current_user)):
    workout = get_workout_by_id(data.workout_id)
    if not workout:
        raise HTTPException(status_code=404, detail="Тренировка не найдена")
    profile = get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Профиль не найден")
    if data.direction not in ("harder", "easier"):
        raise HTTPException(status_code=400, detail="direction must be 'harder' or 'easier'")
    loop = asyncio.get_event_loop()
    new_text = await loop.run_in_executor(
        None, adjust_workout, workout["workout_text"], data.direction, profile
    )
    workout_type = extract_workout_type(new_text)
    distance = extract_distance(new_text)
    new_id = save_workout(user_id, new_text, workout_type, distance)
    return {
        "id": new_id,
        "workout_text": new_text,
        "workout_type": workout_type,
        "distance_meters": distance,
        "completed": False,
        "date": str(date.today()),
    }


@app.post("/api/workout/ask")
async def api_ask_workout(data: WorkoutQuestion, user_id: int = Depends(get_current_user)):
    workout = get_workout_by_id(data.workout_id)
    if not workout:
        raise HTTPException(status_code=404, detail="Тренировка не найдена")
    if not data.question.strip():
        raise HTTPException(status_code=400, detail="Вопрос не может быть пустым")
    loop = asyncio.get_event_loop()
    answer = await loop.run_in_executor(
        None, ask_workout_question, workout["workout_text"], data.question
    )
    return {"answer": answer}


@app.post("/api/workout/log")
async def api_log_workout(data: WorkoutLog, user_id: int = Depends(get_current_user)):
    mark_workout_completed(
        data.workout_id,
        data.perceived_effort,
        data.feedback,
        data.distance_meters,
        data.completion_rate,
        data.actual_distance,
    )
    return {"ok": True}
