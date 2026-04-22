import json
import logging
import re
from datetime import datetime
from openai import OpenAI

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client

SYSTEM_PROMPT = """You are a professional swimming coach with 20 years of experience training athletes of all levels. You create strictly personalised workouts based on scientific methodology and individual swimmer data.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTENSITY LEVELS (use heart rate per 10 sec, never zone numbers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instruct the swimmer to place fingers on neck immediately after a set and count beats for 10 sec. Reference max HR ~31 bpm/10s (185 bpm, formula 220−age ~35). If swimmer doesn't monitor HR — provide RPE feeling as a hint.

Recovery (~18-21/10s): easy breathing, can speak in full sentences
Aerobic (~21-24/10s): can talk, pace sustainable for long time, light effort
Threshold (~24-27/10s): conversation difficult, muscles slightly burn — builds endurance
Speed endurance (~27-29/10s): hard, sustainable 1-2 min, breathing fast
Maximum (~29-31/10s): all-out effort, 15-30 sec only, impossible to speak

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES BY LEVEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BEGINNER (200–800 m per session):
- Primary goal: technique and water confidence, NOT load
- Only recovery and aerobic HR (up to ~24/10s), NO speed sets
- Rest between sets: 60-90 sec
- Short sets: 25-50 m
- Structure: 60% warm-up + drills, 20% main set, 20% cool-down
- Technique drills are mandatory
- Pace: ~2:00 min/100m or slower
- Maximum volume is 800 m REGARDLESS of session duration
- If session > 40 min — increase rest and drills, NOT distance
- MAX sets in main block: 4

INTERMEDIATE (800–2500 m per session):
- Short rest sets (15-30 sec)
- Alternate load: aerobic → speed → technique → recovery
- HR 21-29/10s depending on session goal
- Sets: 4×100m, 6×100m, 8×50m, pyramids (50-100-150-200-150-100-50)
- Technique drills: 15-20% of total volume
- Pace: 1:30-2:00 min/100m
- MAX sets in main block: 8

ADVANCED (2500+ m per session):
- All HR ranges, complex sets
- Pyramids, descending sets, pace-build sets
- Minimal rest (10-20 sec) in aerobic sets
- Speed sets with full recovery (45-90 sec)
- Pace: 1:10-1:30 min/100m
- MAX sets in main block: 12

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TECHNIQUE DRILLS BY STROKE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Freestyle: Fist drill, Zipper (thumb to thigh on recovery), 6-kick switch, kick with board
Backstroke: Single-arm, board on chest (legs only), count strokes to wall
Breaststroke: Arms breaststroke + freestyle kick, breaststroke kick on back, glide 2-3 sec per stroke
Butterfly: Single-arm, 3-3-3 drill, legs only with board (wave from hips not knees)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROGRESSION LOGIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Never increase volume more than 10% from the previous workout
2. Every 4 workouts assign a recovery session (70% of usual volume)
3. If last RPE was 8-10: reduce volume 10-15% and add technique drills
4. If last RPE was 5-7:
   - Last session was ENDURANCE or RECOVERY → increase volume 5-10%
   - Last session was SPEED or TECHNIQUE → add one speed set instead
5. If last RPE was 1-4: increase volume 10-15% AND add 1 higher-HR set
6. Rotate focus: endurance → speed → technique → endurance
7. If a complaint repeats in comments (pain, fatigue in specific area) — reduce load on that area immediately
8. If swimmer missed more than 7 days — return to volume of two workouts ago

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GOAL-BASED APPROACH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Weight loss: 70-80% aerobic HR (~21-24/10s), 1-2 speed sets, priority = more meters
General fitness: balanced mix of all HR ranges, variety of strokes and pyramids
Competition: race-pace sets, starts and turns work (15-25m from wall), HR 27-31/10s
Technique: 40-50% technique drills, slow swimming, 25-50m full effort after each drill

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PACE REFERENCE (for time calculations)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Beginner: ~2:00-2:30/100m | Intermediate: ~1:30-2:00/100m | Advanced: ~1:10-1:30/100m
Rest between sets takes 20-40% of total session time.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (follow exactly — character by character)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The swimmer reads this on a phone at the pool. They must instantly find each task and understand: what to swim, how to swim it, why. Use exactly this template:

🏊 ТРЕНИРОВКА — [ВЫНОСЛИВОСТЬ / СКОРОСТЬ / ТЕХНИКА / ВОССТАНОВЛЕНИЕ]
🏷 ТИП: [то же слово строчными]
⏱ [X] м · ~[Y] мин

━━━━━━━━━━━━━━━━━━━━━━━━
📌 ЗАДАЧА СЕГОДНЯ
━━━━━━━━━━━━━━━━━━━━━━━━
[2-3 предложения живым языком тренера: почему именно такая тренировка сейчас, что будем развивать, чего ждать от ощущений]

━━━━━━━━━━━━━━━━━━━━━━━━
🔥 РАЗМИНКА · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [количество × дистанция, стиль, пульс ~ХХ уд/10с, отдых если есть]
◆ Зачем: [одна фраза]
◆ Как плыть: [2-3 предложения — темп, дыхание, положение тела]

━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ТЕХНИКА · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [количество × дистанция, название упражнения, отдых]
◆ Зачем: [что исправляет или развивает]
◆ Как выполнять: [пошагово — положение тела, движение рук/ног, дыхание, типичные ошибки]
◆ Правильное ощущение: [как должно чувствоваться, если делаешь верно]

━━━━━━━━━━━━━━━━━━━━━━━━
💪 ОСНОВНАЯ ЧАСТЬ · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [количество × дистанция · стиль · отдых · пульс ~ХХ уд/10с]
◆ Зачем: [цель серии]
◆ Как плыть: [темп, ритм дыхания, где должно гореть, как понять что держишь нужный пульс]
◆ В паузе: [что делать во время отдыха]

━━━━━━━━━━━━━━━━━━━━━━━━
🧘 ЗАМИНКА · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [дистанция, стиль, пульс ~ХХ уд/10с]
◆ Как плыть: [очень медленно, тянуться, свободное дыхание]

━━━━━━━━━━━━━━━━━━━━━━━━
💬 ОТ ТРЕНЕРА
━━━━━━━━━━━━━━━━━━━━━━━━
▸ Акцент сегодня: [главное техническое ощущение]
▸ Следи за: [конкретная вещь исходя из истории пловца]
▸ Тренировка удалась, если: [как пловец поймёт что всё сделал правильно]

DISTANCE RULES (mandatory):
- Every set distance MUST be a multiple of 50 m (50, 100, 150, 200, 250, 300, 400, 500, 600 …)
- No set can be 0 m. Every section (РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА) must contain at least one set with distance > 0 m.

IMPORTANT: Write the ENTIRE workout in Russian language only. Do not use any English words in the output. Strictly follow the template — symbols ▸ and ◆ are mandatory before every bullet point."""


def _days_since(date_str: str) -> int:
    try:
        last = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (datetime.now().date() - last).days
    except Exception:
        return 0


def _effort_trend(completed: list) -> str:
    efforts = [w["perceived_effort"] for w in completed[:3] if w["perceived_effort"]]
    if len(efforts) < 2:
        return ""
    if efforts[0] > efforts[-1]:
        return "нагрузка нарастает (последние оценки растут)"
    if efforts[0] < efforts[-1]:
        return "нагрузка снижается (последние оценки падают)"
    return "нагрузка стабильна"


def _repeated_complaints(completed: list) -> str:
    feedbacks = [w["feedback"] for w in completed[:5] if w["feedback"]]
    if not feedbacks:
        return ""
    return "; ".join(feedbacks)


def _build_history_context(history: list) -> str:
    from collections import Counter
    completed = [w for w in history if w["completed"]]
    if not completed:
        return (
            "\n\nHISTORY: no completed workouts yet. "
            "Build a baseline workout for the swimmer's current level."
        )

    lines = ["\n\nANALYTICS AND HISTORY:"]

    days_off = _days_since(completed[0]["date"])
    if days_off > 7:
        lines.append(f"⚠️ Break: {days_off} days without training — reduce volume to the level of two workouts ago.")
    else:
        lines.append(f"Rest days since last workout: {days_off}.")

    count = len(completed)
    if count % 4 == 0:
        lines.append(f"🔄 Every 4 workouts = recovery workout. This is workout #{count + 1}: assign a light recovery session (70% of usual volume).")

    trend = _effort_trend(completed)
    if trend:
        lines.append(f"Effort trend: {trend}.")

    # Скользящее среднее дистанции и жёсткий лимит следующего объёма
    distances = [w["distance_meters"] for w in completed[:3] if w.get("distance_meters")]
    if distances:
        max_next = int(distances[0] * 1.10)
        avg = int(sum(distances) / len(distances))
        lines.append(
            f"Last {len(distances)} workout volumes: {', '.join(str(d)+' m' for d in distances)}. "
            f"Average: {avg} m. "
            f"MAXIMUM volume for next workout: {max_next} m — do not exceed."
        )

    # Анализ типов последних 4 тренировок
    recent_types = [w.get("workout_type", "") for w in completed[:4] if w.get("workout_type")]
    if recent_types:
        type_counts = Counter(recent_types)
        dominant = type_counts.most_common(1)[0]
        if dominant[1] >= 3:
            lines.append(
                f"⚠️ Focus '{dominant[0]}' repeated {dominant[1]} times in a row — "
                f"you MUST switch to a different workout type."
            )
        else:
            lines.append(f"Last 4 workout types: {', '.join(recent_types)}.")

    complaints = _repeated_complaints(completed)
    if complaints:
        lines.append(f"Swimmer's comments from recent workouts: {complaints}")

    lines.append("\nCOMPLETED WORKOUTS (newest first):")
    for i, w in enumerate(completed[:5], 1):
        parts = [f"#{i}({w['date']})"]
        if w["distance_meters"]:
            parts.append(f"{w['distance_meters']}m")
        if w["perceived_effort"]:
            effort = w["perceived_effort"]
            label = "easy" if effort <= 4 else ("optimal" if effort <= 7 else "hard")
            parts.append(f"RPE{effort}({label})")
        if w.get("workout_type"):
            parts.append(w["workout_type"])
        if w["feedback"]:
            parts.append(f'"{w["feedback"][:50]}"')
        lines.append(" | ".join(parts))

    return "\n".join(lines)


VALIDATOR_PROMPT = """You are a strict swimming methodology expert. Evaluate the workout against 7 criteria.
Respond ONLY with valid JSON (no markdown):

If workout is valid:
{"valid": true, "reason": "", "explanation": "...", "corrected_workout": null}

If workout is invalid — fix ALL violations and return the corrected full workout text:
{"valid": false, "reason": "criterion N: what is violated", "explanation": "...", "corrected_workout": "full corrected workout text in Russian"}

Rules for "explanation": 2-3 sentences in Russian for the swimmer about why this workout is beneficial today.
NEVER mention validation, errors, regeneration, anglicisms, criteria numbers, or any technical meta-information.

Rules for "corrected_workout" when valid=false:
- Rewrite the MINIMUM necessary to fix the violation(s)
- Preserve the original structure, formatting, symbols (▸ ◆ ━), and language (Russian)
- The corrected workout must itself pass all 7 criteria

CRITERIA:

1. Volume matches the swimmer's level:
   • beginner: 200–800 m (recovery: 150–560 m)
   • intermediate: 800–2500 m (recovery: 560–1750 m)
   • advanced: 1500–6000 m (recovery: 1050–4200 m)

2. Injuries/restrictions respected. Forbidden exercise mapping:
   • shoulder/rotator cuff → no butterfly, no wide breaststroke pull
   • knee → no breaststroke kick
   • back/lumbar → no butterfly, no undulating body movements
   • neck → no butterfly, no sudden head turns
   • if no injuries — criterion passes automatically

3. Volume did not increase more than 10% from the previous workout (if history exists).
   If analytics state "MAXIMUM volume for next workout" — that limit must be strictly respected.

4. All 4 sections present: РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА.
   Missing any section = valid: false.

5. Number of sets in main block does not exceed level limit:
   beginner — 4 sets, intermediate — 8 sets, advanced — 12 sets.

6. Workout matches the goal:
   • weight loss → at least 70% of meters in aerobic/threshold range (HR 21-27/10s)
   • competition → at least 1 speed set present (HR 27+/10s)
   • technique → technique drills make up at least 30% of total distance
   • general fitness → any distribution accepted
   If insufficient data — criterion passes automatically.

7. Workout text contains no English words (must be entirely in Russian).
   Even a single English word = valid: false. Fix: translate all English words to Russian.

8. Every set distance must be a multiple of 50 m (50, 100, 150, 200, 250, 300 …), and no set can have distance 0 m.
   Even one non-multiple or zero distance = valid: false.
   Fix: round each offending distance to the nearest multiple of 50 (minimum 50 m). Recalculate section totals and the header line accordingly.

The "explanation" field must always be in Russian."""


def validate_workout(workout_text: str, user_data: dict, history: list) -> tuple[bool, str, str | None]:
    level_map = {
        "beginner": "новичок",
        "intermediate": "средний",
        "advanced": "продвинутый",
    }
    level = level_map.get(user_data.get("level", "beginner"), "новичок")
    injuries = user_data.get("injuries") or "нет"

    completed = [w for w in (history or []) if w["completed"]]
    prev_distance = completed[0]["distance_meters"] if completed and completed[0].get("distance_meters") else None
    prev_line = f"Предыдущий объём: {prev_distance} м." if prev_distance else "Предыдущих тренировок нет."

    user_context = (
        f"Уровень пловца: {level}. "
        f"Травмы/ограничения: {injuries}. "
        f"{prev_line}"
    )

    try:
        response = _get_client().chat.completions.create(
            model="gpt-5.4-mini-2026-03-17",
            max_completion_tokens=3000,
            temperature=0.1,
            messages=[
                {"role": "system", "content": VALIDATOR_PROMPT},
                {"role": "user", "content": f"{user_context}\n\nТРЕНИРОВКА:\n{workout_text}"},
            ],
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        data = json.loads(raw)
        valid = bool(data.get("valid", True))
        explanation = data.get("explanation", "")
        corrected = data.get("corrected_workout") or None
        return valid, explanation, corrected
    except Exception:
        return True, "", None


def generate_workout(user_data: dict, history: list = None) -> tuple[str, str]:
    level_map = {
        "beginner": "Новичок (плохо знает технику, плывёт медленно)",
        "intermediate": "Средний уровень (уверенная техника, 1-2 км за тренировку)",
        "advanced": "Продвинутый (соревновательный уровень, 3+ км за тренировку)",
    }
    goal_map = {
        "fitness": "Общая физическая форма и здоровье",
        "weight_loss": "Снижение веса (высокий пульс, кардио)",
        "competition": "Подготовка к соревнованиям (скорость, специфика)",
        "technique": "Улучшение техники (технические упражнения, качество движений)",
    }
    strokes_map = {
        "freestyle": "вольный стиль",
        "backstroke": "на спине",
        "breaststroke": "брасс",
        "butterfly": "баттерфляй",
        "all": "все стили",
    }

    level = level_map.get(user_data.get("level", "beginner"), "Новичок")
    goal = goal_map.get(user_data.get("goal", "fitness"), "Общая физическая форма")
    pool = user_data.get("pool_length", "25")
    duration = user_data.get("duration", "60")
    sessions = user_data.get("sessions_per_week", "3")
    strokes = ", ".join(
        strokes_map.get(s, s) for s in user_data.get("strokes", ["freestyle"])
    )
    injuries = user_data.get("injuries") or "нет"
    pace = user_data.get("best_100m_time")
    pace_line = f"• Личный темп на 100 м: {pace} — рассчитывай интервалы от этого времени\n" if pace else ""

    history_context = _build_history_context(history or [])

    completed = [w for w in (history or []) if w["completed"]]
    workout_number = len(completed) + 1

    from collections import Counter
    recent_types = [w.get("workout_type", "") for w in completed[:3] if w.get("workout_type")]
    type_freq = Counter(recent_types)
    if type_freq.get("выносливость", 0) >= 2:
        recommended = "СКОРОСТЬ или ТЕХНИКА"
    elif type_freq.get("скорость", 0) >= 2:
        recommended = "ВЫНОСЛИВОСТЬ или ТЕХНИКА"
    elif type_freq.get("техника", 0) >= 2:
        recommended = "ВЫНОСЛИВОСТЬ или СКОРОСТЬ"
    else:
        recommended = "по логике прогрессии"

    prompt = (
        f"ПРОФИЛЬ ПЛОВЦА:\n"
        f"• Уровень: {level}\n"
        f"• Цель: {goal}\n"
        f"• Бассейн: {pool} м\n"
        f"• Время на тренировку: {duration} мин\n"
        f"• Тренировок в неделю: {sessions}\n"
        f"• Предпочитаемые стили: {strokes}\n"
        f"• Травмы/ограничения: {injuries}\n"
        f"{pace_line}"
        f"• Номер тренировки у пловца: #{workout_number}"
        f"{history_context}\n\n"
        f"Составь тренировку типа {recommended}. "
        f"Строго соблюди лимит серий для уровня. "
        f"Все 4 секции (РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА) обязательны. "
        f"Учти травмы при подборе упражнений."
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    response = _get_client().chat.completions.create(
        model="gpt-5.4-mini-2026-03-17",
        max_completion_tokens=2048,
        temperature=0.7,
        messages=messages,
    )
    workout_text = response.choices[0].message.content

    valid, explanation, corrected = validate_workout(workout_text, user_data, history or [])
    if valid:
        return workout_text, explanation

    logging.warning("Валидация не прошла. Используем исправленную версию от валидатора.")
    if corrected:
        return corrected, explanation

    logging.error("Валидатор не вернул исправленную тренировку. Отправляем оригинал.")
    return workout_text, ""


def extract_distance(workout_text: str):
    # Формат заголовка: ⏱ 1500 м · ~60 мин
    match = re.search(r'⏱\s*(\d[\d\s]*)\s*м', workout_text)
    if match:
        return int(match.group(1).replace(" ", ""))
    # Запасной вариант
    match = re.search(r"Общий объём[:\s]+(\d[\d\s]*)\s*м", workout_text)
    if match:
        return int(match.group(1).replace(" ", ""))
    return None


def extract_workout_type(workout_text: str) -> str:
    match = re.search(r"ТИП:\s*(\S+)", workout_text)
    if match:
        t = match.group(1).strip(".,").lower()
        for valid in ["выносливость", "скорость", "техника", "восстановление"]:
            if valid.startswith(t[:6]):
                return valid
    lower = workout_text.lower()
    if "восстанов" in lower[:400]:
        return "восстановление"
    if "техник" in lower[:200]:
        return "техника"
    if "скорост" in lower[:200]:
        return "скорость"
    return "выносливость"
