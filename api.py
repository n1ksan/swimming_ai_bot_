import hashlib
import hmac
import json
import os
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
    update_user_field,
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


class ProfileUpdate(BaseModel):
    field: str
    value: str


class WorkoutLog(BaseModel):
    workout_id: int
    perceived_effort: int
    feedback: str = ""
    distance_meters: int = None
    completion_rate: str = "full"
    actual_distance: int = None


@app.get("/api/stats")
async def api_stats(user_id: int = Depends(get_current_user)):
    return get_stats(user_id)


@app.get("/api/history")
async def api_history(user_id: int = Depends(get_current_user)):
    history = get_workout_history(user_id, limit=20)
    for w in history:
        w.pop("workout_text", None)
    return history


@app.get("/api/week")
async def api_week(user_id: int = Depends(get_current_user)):
    return get_week_workouts(user_id)


@app.get("/api/workout/{workout_id}")
async def api_workout(workout_id: int, user_id: int = Depends(get_current_user)):
    w = get_workout_by_id(workout_id)
    if not w:
        raise HTTPException(status_code=404, detail="Тренировка не найдена")
    return w


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
