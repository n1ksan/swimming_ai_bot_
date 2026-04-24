import json
import logging
import os
import random
import re
from datetime import datetime
from openai import OpenAI

_client = None
_exercises_cache = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _load_exercises() -> list:
    global _exercises_cache
    if _exercises_cache is None:
        path = os.path.join(os.path.dirname(__file__), "exercises.json")
        with open(path, encoding="utf-8") as f:
            _exercises_cache = json.load(f)
    return _exercises_cache


# ──────────────────────────────────────────────
# Общие секции промтов
# ──────────────────────────────────────────────

_INTENSITY_SECTION = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INTENSITY LEVELS (use heart rate per 10 sec, never zone numbers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Instruct the swimmer to place fingers on neck immediately after a set and count beats for 10 sec. Reference max HR ~31 bpm/10s (185 bpm, formula 220−age ~35). If swimmer doesn't monitor HR — provide RPE feeling as a hint.

Recovery (~18-21/10s): easy breathing, can speak in full sentences
Aerobic (~21-24/10s): can talk, pace sustainable for long time, light effort
Threshold (~24-27/10s): conversation difficult, muscles slightly burn — builds endurance
Speed endurance (~27-29/10s): hard, sustainable 1-2 min, breathing fast
Maximum (~29-31/10s): all-out effort, 15-30 sec only, impossible to speak"""

_PROGRESSION_SECTION = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
8. If swimmer missed more than 7 days — return to volume of two workouts ago"""

_GOAL_SECTION = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GOAL-BASED APPROACH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Weight loss: 70-80% aerobic HR (~21-24/10s), 1-2 speed sets, priority = more meters
General fitness: balanced mix of all HR ranges, variety of strokes and pyramids
Competition: race-pace sets, starts and turns work (15-25m from wall), HR 27-31/10s
Technique: 40-50% technique drills, slow swimming, 25-50m full effort after each drill"""

_OUTPUT_FORMAT_SECTION = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (follow exactly — character by character)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The swimmer reads this on a phone at the pool. They must instantly scan the action line and then read the details below. Use exactly this template:

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

▸ [N ×] [дистанция] м  [стиль / название]
❤️ Пульс: ~ХХ уд/10 сек ([название зоны])
⏱ Отдых: [X сек] или [нет]
📖 Как плыть: [2-3 предложения — темп, дыхание, положение тела]
💡 Зачем: [одна фраза]

━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ТЕХНИКА · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [N ×] [дистанция] м  [название упражнения]
💡 Зачем: [что исправляет или развивает]
📖 Как выполнять: [пошагово — положение тела, движение рук/ног, дыхание, типичные ошибки]
✅ Правильное ощущение: [как должно чувствоваться, если делаешь верно]
⏱ Отдых: [X сек]

━━━━━━━━━━━━━━━━━━━━━━━━
💪 ОСНОВНАЯ ЧАСТЬ · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [N ×] [дистанция] м  [стиль] [пометка: «ноги» / «руки» / «нарастание» / «пирамида» если применимо]
❤️ Пульс: ~ХХ уд/10 сек ([название зоны])
⏱ Отдых: [X сек]   ← или ⏱ Режим: стартуешь каждые [M:SS]
📖 Как плыть: [темп, ритм дыхания, где должно гореть]
💡 Зачем: [цель серии]
⏸ В паузе: [что делать во время отдыха — только если отдых ≥ 30 сек]

Если известны зоны темпа из профиля:
🎯 Целевой темп: [MM:SS]/100 м

━━━━━━━━━━━━━━━━━━━━━━━━
🧘 ЗАМИНКА · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

▸ [дистанция] м  [стиль — выбор]
❤️ Пульс: ~18–20 уд/10 сек (восстановительный)
📖 Как плыть: очень медленно, тянуться в каждом гребке, свободное дыхание

━━━━━━━━━━━━━━━━━━━━━━━━
💬 ОТ ТРЕНЕРА
━━━━━━━━━━━━━━━━━━━━━━━━
▸ Акцент сегодня: [главное техническое ощущение]
▸ Следи за: [конкретная вещь исходя из истории пловца]
▸ Тренировка удалась, если: [как пловец поймёт что всё сделал правильно]

Слова «цикл» и «отправление» НЕ использовать. Только «Отдых» или «Режим»."""

_RULES_SECTION = """DISTANCE RULES (mandatory):
- Every set distance MUST be a multiple of 50 m (50, 100, 150, 200, 250, 300, 400, 500, 600 …)
- No set can be 0 m. Every section (РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА) must contain at least one set with distance > 0 m.
- If pool length = 50 m: minimum set distance is 50 m. Never write sets of 25 m in a 50 m pool.

FORMAT RULES (mandatory):
- The ▸ action line contains ONLY: count × distance м  stroke/exercise name. Nothing else on that line.
- ALL details (pulse, rest, how-to, goal, pace) go on the sub-lines with icons ❤️ ⏱ 📖 💡 ✅ ⏸ 🎯
- Never mix pulse/rest/description into the ▸ line.
- Icons ❤️ ⏱ 📖 💡 ✅ ⏸ 🎯 replace ◆ on all sub-lines. Do NOT use ◆ for sub-lines.
- The ▸ symbol is still used only on action lines.
- One "set" = one ▸ line. "4×100 м" is 1 set, not 4. The level set limit applies to ▸ lines inside ОСНОВНАЯ ЧАСТЬ only.

IMPORTANT: Write the ENTIRE workout in Russian language only. Do not use any English words in the output. Strictly follow the template."""


# ──────────────────────────────────────────────
# Три уровне-специфичных системных промта
# ──────────────────────────────────────────────

SYSTEM_PROMPT_BEGINNER = f"""You are a professional swimming coach training a beginner swimmer. Your primary goal is technique, water confidence, and making every session enjoyable — NOT performance or volume. The swimmer is still learning body position, breathing, and basic stroke mechanics.

{_INTENSITY_SECTION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES FOR BEGINNER (СТРОГО ОБЯЗАТЕЛЬНО)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Total volume: 200–800 m per session
- ONLY Recovery and Aerobic HR (up to ~24/10s). NO speed sets, NO threshold work
- Rest between sets: 60–90 sec
- Short sets: 25–50 m
- Maximum sets in ОСНОВНАЯ ЧАСТЬ: 4

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKOUT STRUCTURE FOR BEGINNER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ТЕХНИКА section must contain 3–4 exercises and make up 60–70% of total volume
- ОСНОВНАЯ ЧАСТЬ: simple continuous lengths at easy/aerobic pace, max 4 sets
- РАЗМИНКА: 3 elements — easy swimming, a short 2–3 length progressive series, leg kick drill (2×25 м with or without board)
- The swimmer's session is mostly about learning — not racing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE IN ✅ ПРАВИЛЬНОЕ ОЩУЩЕНИЕ (в разделе ТЕХНИКА)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use the provided correct_feeling text for each exercise (it will be given in the user message).
Tone must be warm and encouraging. Use the exact feeling text provided — do NOT rewrite it.
Example style: "Ты почувствуешь..." / "Это нормально если..." / "Обрати внимание на..."

{_PROGRESSION_SECTION}

{_GOAL_SECTION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PACE REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Beginner: ~2:00–2:30/100 m. Rest between sets takes 30–50% of total session time.

{_OUTPUT_FORMAT_SECTION}

ОСНОВНАЯ ЧАСТЬ для новичка:
- НЕ требуется серия ноги или серия руки с инвентарём
- Простые длины в лёгком темпе. Если есть доска — можно добавить ноги с доской

{_RULES_SECTION}"""


SYSTEM_PROMPT_INTERMEDIATE = f"""You are a professional swimming coach training an intermediate swimmer. They have solid technique foundations, swim consistently 2–4 times per week, and are ready for structured training with varied intensity.

{_INTENSITY_SECTION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES FOR INTERMEDIATE (СТРОГО ОБЯЗАТЕЛЬНО)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Total volume: 800–2500 m per session
- HR 21–29/10s depending on session goal
- Short rest in aerobic work: 15–30 sec
- Sets: 4×100m, 6×100m, 8×50m, pyramids (50-100-150-200-150-100-50)
- Technique drills: 15–20% of total volume
- Maximum sets in ОСНОВНАЯ ЧАСТЬ: 8

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKOUT STRUCTURE FOR INTERMEDIATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ТЕХНИКА section: 3–5 exercises from the provided list
- ОСНОВНАЯ ЧАСТЬ: full structured sets with proper HR targets and rest management
- РАЗМИНКА: easy swimming 200–400 m, progressive series 4×[25 or 50 m], kick drill 2×[25 or 50 m]
- In sessions ≥ 45 min, include at least 1 legs set and 1 arms set in ОСНОВНАЯ ЧАСТЬ (only if equipment is available)
- Include at least 1 progressive series (ascending / pyramid / descending rest) in ОСНОВНАЯ ЧАСТЬ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE IN ✅ ПРАВИЛЬНОЕ ОЩУЩЕНИЕ (в разделе ТЕХНИКА)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Use the provided correct_feeling text for each exercise (it will be given in the user message).
Tone must be specific and technical. Use the exact feeling text provided — do NOT rewrite it.
Example style: "Давление воды на предплечье..." / "Ощущение правильного захвата..."

{_PROGRESSION_SECTION}

{_GOAL_SECTION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PACE REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Intermediate: ~1:30–2:00/100 m. Rest between sets takes 20–40% of total session time.

{_OUTPUT_FORMAT_SECTION}

{_RULES_SECTION}"""


SYSTEM_PROMPT_ADVANCED = f"""You are a professional swimming coach training an advanced competitive swimmer. They train at high volume, understand periodization, and can handle complex sets and pace work.

{_INTENSITY_SECTION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES FOR ADVANCED (СТРОГО ОБЯЗАТЕЛЬНО)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Total volume: 2500+ m per session
- All HR ranges used, including maximum
- Pyramids, descending sets, pace-build sets
- Minimal rest (10–20 sec) in aerobic sets
- Speed sets with full recovery (45–90 sec)
- Maximum sets in ОСНОВНАЯ ЧАСТЬ: 12

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WORKOUT STRUCTURE FOR ADVANCED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- ТЕХНИКА section: 3–5 exercises from the provided list (10–15% of total volume)
- ОСНОВНАЯ ЧАСТЬ: intensive complex sets with precise pace targets
- РАЗМИНКА: easy swimming 400 m, progressive series 4×[50 m], kick drill 2×[50 m]
- In sessions ≥ 45 min, include at least 1 legs set and 1 arms set (if equipment available)
- Include at least 1 complex set (pyramid / pace descend / interval)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ ПРАВИЛЬНОЕ ОЩУЩЕНИЕ — CRITICAL RULE FOR ADVANCED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ lines are ONLY allowed inside the ТЕХНИКА section.
Do NOT write ✅ lines in РАЗМИНКА, ОСНОВНАЯ ЧАСТЬ, or ЗАМИНКА.
In ТЕХНИКА: use the provided correct_feeling text — keep it as one concise sentence, professional tone.
Example style: "Давление на предплечье от локтя до запястья." / "Бёдра ведут вращение."

{_PROGRESSION_SECTION}

{_GOAL_SECTION}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PACE REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Advanced: ~1:10–1:30/100 m. Rest between sets takes 10–25% of total session time.

{_OUTPUT_FORMAT_SECTION}

{_RULES_SECTION}"""


# ──────────────────────────────────────────────
# Вспомогательные функции: упражнения
# ──────────────────────────────────────────────

def _injuries_match(exercise: dict, injuries_text: str) -> bool:
    """True если упражнение НЕ подходит из-за травм."""
    if not injuries_text or injuries_text.strip().lower() in ("нет", "no", "-", ""):
        return False
    inj = injuries_text.lower()
    for tag in exercise.get("injuries_avoid", []):
        if tag == "shoulder" and any(w in inj for w in ("плеч", "ротатор", "shoulder")):
            return True
        if tag == "knee" and any(w in inj for w in ("колен", "knee")):
            return True
        if tag == "back" and any(w in inj for w in ("спин", "поясниц", "back", "lumbar")):
            return True
        if tag == "neck" and any(w in inj for w in ("шея", "шей", "neck")):
            return True
    return False


def select_exercises(profile: dict, history: list, count: int = 4) -> list:
    """Выбирает count упражнений для ТЕХНИКА с учётом уровня, стилей, травм, инвентаря и ротации."""
    exercises = _load_exercises()
    level = profile.get("level", "beginner")
    strokes = set(profile.get("strokes") or ["freestyle"])
    if "all" in strokes:
        strokes = {"freestyle", "backstroke", "breaststroke", "butterfly"}
    injuries = profile.get("injuries") or ""
    equipment = set(profile.get("equipment") or [])

    recently_used = set()
    for w in (history or [])[:3]:
        for ex_id in (w.get("used_exercises") or []):
            recently_used.add(ex_id)

    def matches(ex: dict) -> bool:
        if level not in ex.get("level", []):
            return False
        if not set(ex.get("stroke", [])) & strokes:
            return False
        if _injuries_match(ex, injuries):
            return False
        required_eq = set(ex.get("equipment", []))
        if required_eq and not required_eq.issubset(equipment):
            return False
        return True

    candidates = [ex for ex in exercises if matches(ex)]
    fresh = [ex for ex in candidates if ex["id"] not in recently_used]
    pool = fresh if len(fresh) >= count else candidates

    random.shuffle(pool)
    return pool[:count]


def _format_exercises_for_prompt(exercises: list, level: str) -> str:
    """Форматирует список упражнений для вставки в пользовательский промт."""
    if not exercises:
        return ""
    lines = [
        "УПРАЖНЕНИЯ ДЛЯ РАЗДЕЛА ТЕХНИКА:",
        "Используй только из этого списка. Не придумывай других упражнений.\n",
    ]
    feeling_key = f"correct_feeling_{level}"
    for ex in exercises:
        dist = "–".join(str(d) for d in ex.get("typical_distances", [25, 50]))
        lines.append(f"▸ {ex['name']}  ({dist} м)")
        lines.append(f"💡 Зачем: {ex['why']}")
        lines.append(f"📖 Как выполнять: {ex['how_to']}")
        feeling = ex.get(feeling_key) or ex.get("correct_feeling_intermediate")
        if feeling:
            lines.append(f"✅ Правильное ощущение: {feeling}")
        lines.append("")
    return "\n".join(lines)


def _select_system_prompt(profile: dict) -> str:
    level = profile.get("level", "beginner")
    return {
        "beginner": SYSTEM_PROMPT_BEGINNER,
        "intermediate": SYSTEM_PROMPT_INTERMEDIATE,
        "advanced": SYSTEM_PROMPT_ADVANCED,
    }.get(level, SYSTEM_PROMPT_BEGINNER)


# ──────────────────────────────────────────────
# Вспомогательные функции: история и темп
# ──────────────────────────────────────────────

def _calc_pace_zones(best_100m: str | None) -> dict | None:
    if not best_100m:
        return None
    try:
        parts = best_100m.strip().split(":")
        base = int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None
    def fmt(s: int) -> str:
        return f"{s // 60}:{s % 60:02d}"
    return {
        "recovery":  fmt(int(base * 1.30)),
        "aerobic":   fmt(int(base * 1.15)),
        "threshold": fmt(int(base * 1.07)),
        "speed":     fmt(int(base * 0.98)),
    }


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


def _recommend_workout_type(completed: list) -> str:
    from collections import Counter
    recent_types = [w.get("workout_type", "") for w in completed[:3] if w.get("workout_type")]
    type_freq = Counter(recent_types)
    if type_freq.get("выносливость", 0) >= 2:
        return "СКОРОСТЬ или ТЕХНИКА"
    if type_freq.get("скорость", 0) >= 2:
        return "ВЫНОСЛИВОСТЬ или ТЕХНИКА"
    if type_freq.get("техника", 0) >= 2:
        return "ВЫНОСЛИВОСТЬ или СКОРОСТЬ"
    return "по логике прогрессии"


def _build_history_context(history: list) -> str:
    completed = [w for w in history if w["completed"]]
    if not completed:
        return (
            "\n\nИСТОРИЯ: завершённых тренировок нет. "
            "Составь базовую тренировку для текущего уровня пловца."
        )

    lines = ["\n\nАНАЛИТИКА:"]

    days_off = _days_since(completed[0]["date"])
    if days_off > 7:
        lines.append(f"⚠️ Перерыв {days_off} дней — снизить объём до уровня двух тренировок назад.")
    else:
        lines.append(f"Дней отдыха с последней тренировки: {days_off}.")

    count = len(completed)
    if count % 4 == 0:
        lines.append(f"🔄 Каждые 4 тренировки = восстановительная. Это тренировка #{count + 1}: лёгкая, 70% обычного объёма.")

    trend = _effort_trend(completed)
    if trend:
        lines.append(f"Тренд нагрузки: {trend}.")

    distances = [w["distance_meters"] for w in completed[:3] if w.get("distance_meters")]
    if distances:
        max_next = int(distances[0] * 1.10)
        avg = int(sum(distances) / len(distances))
        lines.append(
            f"Объёмы последних {len(distances)} тренировок: {', '.join(str(d)+' м' for d in distances)}. "
            f"Среднее: {avg} м. "
            f"МАКСИМУМ следующей тренировки: {max_next} м — не превышать."
        )

    complaints = _repeated_complaints(completed)
    if complaints:
        lines.append(f"Комментарии пловца: {complaints}")

    lines.append("\nВЫПОЛНЕННЫЕ ТРЕНИРОВКИ (новые первыми):")
    for i, w in enumerate(completed[:5], 1):
        parts = [f"#{i}({w['date']})"]
        if w["distance_meters"]:
            parts.append(f"{w['distance_meters']}м")
        if w["perceived_effort"]:
            effort = w["perceived_effort"]
            label = "легко" if effort <= 4 else ("оптимально" if effort <= 7 else "тяжело")
            parts.append(f"RPE{effort}({label})")
        if w.get("workout_type"):
            parts.append(w["workout_type"])
        if w["feedback"]:
            parts.append(f'"{w["feedback"][:50]}"')
        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ──────────────────────────────────────────────
# Валидатор
# ──────────────────────────────────────────────

VALIDATOR_PROMPT = """You are a strict swimming methodology expert. Evaluate the workout against 8 criteria.
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
   • advanced: 2500–6000 m (recovery: 1750–4200 m)

2. Injuries/restrictions respected. Forbidden exercise mapping:
   • shoulder/rotator cuff → no butterfly, no wide breaststroke pull
   • knee → no breaststroke kick
   • back/lumbar → no butterfly, no undulating body movements
   • neck → no butterfly, no sudden head turns
   • if no injuries — criterion passes automatically

3. Volume did not increase more than 10% from the previous workout (if history exists).
   If analytics state "МАКСИМУМ следующей тренировки" — that limit must be strictly respected.
   SKIP this criterion if there are no previous completed workouts (first session).

4. All 4 sections present: РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА.
   Missing any section = valid: false.

5. Number of sets in ОСНОВНАЯ ЧАСТЬ section does not exceed level limit:
   beginner — 4 sets, intermediate — 8 sets, advanced — 12 sets.
   One "set" = one ▸ line (e.g. "4×100 м" = 1 set, not 4). Count only ▸ lines inside ОСНОВНАЯ ЧАСТЬ, not РАЗМИНКА or ТЕХНИКА.

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


# ──────────────────────────────────────────────
# Генерация тренировки
# ──────────────────────────────────────────────

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
    equipment_map = {
        "kickboard": "доска",
        "pull_buoy": "колобашка",
        "paddles": "лопатки",
        "fins": "ласты",
        "snorkel": "трубка",
        "band": "резинка (стяжка на лодыжки)",
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
    usual_dist = user_data.get("usual_distance")

    equipment_raw = user_data.get("equipment") or []
    if isinstance(equipment_raw, str):
        try:
            equipment_raw = json.loads(equipment_raw)
        except Exception:
            equipment_raw = []
    equipment_line = (
        f"• Доступный инвентарь: {', '.join(equipment_map.get(e, e) for e in equipment_raw)}\n"
        if equipment_raw
        else "• Инвентарь: нет (только тело)\n"
    )

    usual_dist_line = (
        f"• Обычный объём пловца за тренировку: {usual_dist} м — "
        f"используй как базовый ориентир для первой тренировки (если нет истории)\n"
    ) if usual_dist else ""

    zones = _calc_pace_zones(pace)
    if zones and pace:
        pace_line = (
            f"• Личный темп на 100 м: {pace}\n"
            f"• ЗОНЫ ТЕМПА (используй для 🎯 Целевой темп в сериях):\n"
            f"    - Восстановление: {zones['recovery']}/100 м\n"
            f"    - Аэробная:       {zones['aerobic']}/100 м\n"
            f"    - Порог (CSS):    {zones['threshold']}/100 м\n"
            f"    - Скорость:       {zones['speed']}/100 м\n"
        )
    elif pace:
        pace_line = f"• Личный темп на 100 м: {pace} — рассчитывай интервалы от этого времени\n"
    else:
        pace_line = ""

    days_map = {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт", "fri": "Пт", "sat": "Сб", "sun": "Вс"}
    weekday_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    training_days = user_data.get("training_days") or []
    if isinstance(training_days, str):
        try:
            training_days = json.loads(training_days)
        except Exception:
            training_days = []
    today_key = weekday_keys[datetime.now().weekday()]
    training_days_line = ""
    if training_days:
        days_ru = [days_map.get(d, d) for d in training_days]
        yesterday_key = weekday_keys[(weekday_keys.index(today_key) - 1) % 7]
        tomorrow_key = weekday_keys[(weekday_keys.index(today_key) + 1) % 7]
        load_hint = []
        if yesterday_key in training_days:
            load_hint.append("вчера была тренировка → не делай две тяжёлые подряд")
        if tomorrow_key in training_days:
            load_hint.append("завтра тоже тренировка → оставь запас сил")
        hint_str = "; ".join(load_hint)
        training_days_line = (
            f"• Дни тренировок: {', '.join(days_ru)}\n"
            f"• Сегодня: {days_map.get(today_key, '?')}"
            + (f" — {hint_str}" if hint_str else "") + "\n"
        )

    history_context = _build_history_context(history or [])

    completed = [w for w in (history or []) if w["completed"]]
    workout_number = len(completed) + 1
    recommended = _recommend_workout_type(completed)

    # Выбрать и отформатировать упражнения для ТЕХНИКА
    level_key = user_data.get("level", "beginner")
    ex_count = 3 if level_key == "beginner" else 4
    selected_exercises = select_exercises(user_data, history or [], count=ex_count)
    exercises_block = _format_exercises_for_prompt(selected_exercises, level_key)
    used_exercise_ids = [ex["id"] for ex in selected_exercises]

    prompt = (
        f"ПРОФИЛЬ ПЛОВЦА:\n"
        f"• Уровень: {level}\n"
        f"• Цель: {goal}\n"
        f"• Бассейн: {pool} м\n"
        f"• Время на тренировку: {duration} мин\n"
        f"• Тренировок в неделю: {sessions}\n"
        f"• Предпочитаемые стили: {strokes}\n"
        f"• Травмы/ограничения: {injuries}\n"
        f"{equipment_line}"
        f"{usual_dist_line}"
        f"{pace_line}"
        f"{training_days_line}"
        f"• Номер тренировки у пловца: #{workout_number}"
        f"{history_context}\n\n"
        f"{exercises_block}\n"
        f"Составь тренировку типа {recommended}. "
        f"Строго соблюди лимит серий для уровня. "
        f"Все 4 секции (РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА) обязательны. "
        f"Учти травмы при подборе упражнений."
    )

    messages = [
        {"role": "system", "content": _select_system_prompt(user_data)},
        {"role": "user", "content": prompt},
    ]

    response = _get_client().chat.completions.create(
        model="gpt-5.4-mini-2026-03-17",
        max_completion_tokens=2048,
        temperature=0.7,
        messages=messages,
    )
    workout_text = fix_section_distances(response.choices[0].message.content)

    valid, explanation, corrected = validate_workout(workout_text, user_data, history or [])
    if valid:
        return workout_text, explanation, used_exercise_ids

    logging.warning("Валидация не прошла. Используем исправленную версию от валидатора.")
    if corrected:
        return fix_section_distances(corrected), explanation, used_exercise_ids

    logging.error("Валидатор не вернул исправленную тренировку. Отправляем оригинал.")
    return workout_text, "", used_exercise_ids


# ──────────────────────────────────────────────
# Утилиты: дистанции и тип тренировки
# ──────────────────────────────────────────────

def _sum_sets(lines: list[str]) -> int:
    """Суммирует дистанции всех строк ▸ в списке строк."""
    total = 0
    for line in lines:
        s = line.strip()
        if not s.startswith('▸'):
            continue
        m = re.search(r'(\d+)\s*[×xхХ]\s*(\d+)', s)
        if m:
            n, d = int(m.group(1)), int(m.group(2))
            if 1 <= n <= 50 and 25 <= d <= 3000:
                total += n * d
        else:
            m = re.search(r'(\d+)\s*м', s)
            if m:
                d = int(m.group(1))
                if 25 <= d <= 3000:
                    total += d
    return total


def fix_section_distances(workout_text: str) -> str:
    """Пересчитывает дистанции в заголовках секций и итоговой строке ⏱."""
    lines = workout_text.split('\n')
    result: list[str] = []
    i = 0

    def is_sep(line: str) -> bool:
        s = line.strip()
        return bool(s) and all(c == '━' for c in s)

    while i < len(lines):
        if (is_sep(lines[i])
                and i + 2 < len(lines)
                and lines[i + 1].strip()
                and not is_sep(lines[i + 1])
                and is_sep(lines[i + 2])):

            result.append(lines[i])
            header = lines[i + 1]
            header_idx = len(result)
            result.append(header)
            result.append(lines[i + 2])
            i += 3

            content: list[str] = []
            while i < len(lines) and not is_sep(lines[i]):
                content.append(lines[i])
                i += 1

            real_dist = _sum_sets(content)
            if real_dist > 0:
                result[header_idx] = re.sub(
                    r'·\s*\d[\d\s]*\s*м', f'· {real_dist} м', header
                )
            result.extend(content)
        else:
            result.append(lines[i])
            i += 1

    fixed = '\n'.join(result)

    total = _sum_sets(fixed.split('\n'))
    if total > 0:
        fixed = re.sub(r'(⏱\s*)\d[\d\s]*\s*м', f'\\g<1>{total} м', fixed)

    return fixed


def extract_distance(workout_text: str) -> int | None:
    total = _sum_sets(workout_text.split('\n'))
    if total > 0:
        return total
    m = re.search(r'⏱\s*(\d[\d\s]*)\s*м', workout_text)
    return int(m.group(1).replace(" ", "")) if m else None


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
