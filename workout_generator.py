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

Use these drills in ТЕХНИКА sections. For each drill in the output, fill in all three fields in Russian using emoji icons (never ◆):
💡 Зачем / 📖 Как выполнять (пошагово: положение тела, движение рук/ног, дыхание, типичные ошибки) / ✅ Правильное ощущение.

──── FREESTYLE ────
1. Кулаки (Fist Drill) — плывёшь кролем с плотно сжатыми кулаками. Заставляет использовать предплечье как весло, а не только ладонь.
   How: close fists entirely, swim normal freestyle. Feel the forearm pressing back against the water from catch to hip. At set end, open hands and notice the dramatic improvement in "grip."
   Common mistake: opening fingers slightly — keep full fist. Correct feeling: water pressure on the entire forearm from elbow to wrist.

2. Догонялка (Catch-Up Drill) — одна рука остаётся вытянутой вперёд, пока восстанавливающаяся рука не догонит и не коснётся её.
   How: start with right arm extended, left arm pulls through to hip and recovers forward to touch the right hand — then right arm pulls. Pause at the front on every stroke. Use 6 kicks per arm cycle.
   Common mistake: not waiting for the touch, rushing the cycle. Correct feeling: long glide phase, body rolls fully to each side, each stroke feels deliberate.

3. Волочение пальцами (Fingertip Drag) — во время проноса руки кончики пальцев слегка скользят по поверхности воды.
   How: as the elbow exits the water and leads the recovery high, let only the fingertips skim the surface. Elbow must be higher than the hand at all times.
   Common mistake: elbow drops low or arm swings wide. Correct feeling: high elbow on recovery, hand enters directly in front of shoulder, no wide arc.

4. Боковые удары (Side Kick) — удары ногами на боку, нижняя рука вытянута вперёд, верхняя вдоль тела. Смена сторон каждые 6 ударов.
   How: roll to one side, lower ear in water, lower arm extended forward, upper arm along body. Kick steadily for 6 counts, take one full stroke, rotate to other side, hold 6 kicks. Breathe by rotating head up, not lifting.
   Common mistake: head lifts instead of rotating, hips drop. Correct feeling: hip drives the rotation, body is a flat plank, kick originates from hip not knee.

5. Одна рука (Single Arm Freestyle) — одна рука вдоль тела (или вытянута вперёд), другая делает полный гребок.
   How: non-active arm at hip for easier version, extended for harder. Do 4–6 strokes per arm, then switch. Breathe to the side of the active arm.
   Common mistake: body rocks side to side without rotating through core. Correct feeling: full reach on entry, high elbow catch, pull all the way to hip.

6. Подсчёт гребков (Stroke Count) — считаешь количество гребков на каждые 25 м. Цель — снизить счёт на 1–2 без потери скорости.
   How: push off, count every right-hand entry as one stroke. Record the count. Next length: focus on longer reach and stronger pull to reduce count.
   Common mistake: slowing down drastically to lower count — find the balance of power and efficiency. Correct feeling: each stroke covers more distance, body glides between strokes.

7. Шесть ударов — смена (6-Kick Switch) — 6 ударов на боку, затем один гребок и поворот на другой бок, снова 6 ударов.
   How: same as Боковые удары but with an active stroke to transition between sides. The stroke timing is: kick-kick-kick-kick-kick-kick-PULL-rotate-kick-kick-kick... Focus on the rotation happening exactly when the hand enters the water.
   Common mistake: transition stroke is rushed. Correct feeling: rotation is smooth, not jerky; body arrives on the new side in perfect streamline.

8. Ноги с доской (Kick with Board) — руки на доске, работают только ноги кролем.
   How: hold board with both hands, face down, legs kick from hip. Ankles relaxed, toes pointed. Kick amplitude is narrow (20–30 cm), not wide bicycle-style.
   Common mistake: bending knees excessively, kicking from knee not hip. Correct feeling: entire leg is a long lever moving from hip, feet flick like a whip at the bottom of each kick.

──── BREASTSTROKE ────
1. Пауза-скольжение (Pause/Glide Drill) — полная 3-секундная остановка в позиции скольжения перед следующим циклом гребка.
   How: pull, kick, then hold — arms fully extended in front, legs together, body arrow-straight. Count "one-one-thousand, two-one-thousand, three-one-thousand" before the next pull.
   Common mistake: starting the next pull before legs fully snap together. Correct feeling: the glide carries you forward with no effort; you feel momentum from the kick.

2. Удар брассом на спине (Breaststroke Kick on Back) — лежишь на спине, руки вдоль тела, работают только ноги брассом.
   How: face up, hands on thighs. Bring heels toward buttocks while letting knees drop slightly outward. Rotate feet outward (toes pointing to corners, not down), then drive heels outward and together in a circular motion.
   Common mistake: feet pointing downward instead of outward during the drive. Correct feeling: the instep of the foot presses against the water; you feel the kick in the inner thigh.

3. Руки за спиной (Hands Behind Back) — руки сцеплены за поясницей, работают только ноги брассом, лёжа на груди.
   How: face down, hands clasped at small of back. Kick breaststroke. This forces perfect symmetry — if one leg kicks stronger, you spin.
   Common mistake: asymmetric kick (one leg stronger). Correct feeling: perfectly straight travel, knees come up hip-width, not wider.

4. Два удара на гребок (Two Kicks Per One Pull) — два полных удара брассом на каждый один гребок руками.
   How: pull → kick → glide → kick → glide → pull → kick → glide → kick... The second kick must be as powerful as the first.
   Common mistake: second kick is half-hearted. Correct feeling: each kick has full hip extension and foot snap; the second kick is as strong as the first.

5. Только руки с колобашкой (Arms Only + Pull Buoy) — колобашка между бёдер, ноги пассивны, работают только руки брассом.
   How: hold pull buoy, face down, legs passive. Pull: elbows high, hands sweep out to shoulder width, then in toward chin (like drawing a heart), shoot arms forward into glide.
   Common mistake: hands sweep too wide past shoulders, losing power. Correct feeling: the "catch" happens when elbows are at shoulder height, hands accelerate inward and forward explosively.

──── BUTTERFLY ────
1. Одна рука баттерфляй (Single Arm Butterfly) — ведущая рука вытянута вперёд, другая делает полные гребки баттерфляем. Дыхание в сторону.
   How: left arm extended forward, right arm does full butterfly strokes. Two dolphin kicks per stroke: one when the right hand enters, one when it finishes pulling. After 6 strokes, switch arms.
   Common mistake: forgetting the double kick rhythm. Correct feeling: hips drive each kick, the wave starts at chest, flows through core to feet.

2. Упражнение 3-3-3 (3-3-3 Drill) — 3 гребка правой рукой, 3 гребка левой, 3 гребка полным баттерфляем.
   How: right arm only (left extended) × 3 → left arm only (right extended) × 3 → both arms full butterfly × 3. Repeat.
   Common mistake: losing the kick rhythm when switching. Correct feeling: the transition to full butterfly feels smooth because each arm is already warmed up individually.

3. Дельфин на спине (Dolphin Kick on Back) — лежишь на спине, руки вдоль тела или над головой, полный дельфиньий удар.
   How: face up, body flat. Kick from core: the movement starts at the chest pressing down, hips rise, then knees bend slightly, then feet flick. Like an undulating wave from top to bottom.
   Common mistake: kicking from knees only (bicycle-style), hips barely move. Correct feeling: the whole body undulates — chest, belly, hips, knees, feet in sequence.

4. Баттерфляй с кролевым ударом (Butterfly + Flutter Kick) — гребки баттерфляем, но удары ногами кролем вместо дельфинового.
   How: full butterfly arm stroke but with a steady freestyle kick. Allows full focus on arm timing, breathing position, and catch mechanics without the added difficulty of dolphin kick.
   Common mistake: arms rush because legs feel easy. Correct feeling: long reach on entry, catch happens before hips drop, breathing is forward (chin clears water, not head lifted).

──── BACKSTROKE ────
1. Одна рука на спине (Single Arm Backstroke) — одна рука гребёт, другая вытянута над головой или вдоль тела.
   How: right arm strokes while left stays overhead (harder) or at hip (easier). Pinky finger enters the water first, arm enters behind the shoulder (not crossing the center line). Pull through to hip, recover high.
   Common mistake: hand crosses center line on entry — causes snaking. Correct feeling: shoulder rotates fully, hand enters in line with shoulder, pull is powerful and direct.

2. Доска на груди (Kickboard on Chest) — держишь доску на груди, работают только ноги на спине.
   How: lie on back, hold board flat on chest with both hands. Kick from hip, feet near surface, toes pointed. Kick amplitude narrow (ankles 20–30 cm apart at maximum spread).
   Common mistake: knees break the surface (too much knee bend). Correct feeling: hips are at surface, kick is from hip, toes flick at the top of each kick.

3. Гребки до флажков (Stroke Count to Flags) — плывёшь на спине, считая гребки от флажков 5м до стенки.
   How: when you pass under the flags, start counting each arm stroke. Touch the wall on the same count every length. Build a reliable number (usually 3–6 strokes depending on height and speed).
   Common mistake: inconsistent count because of varying push-off strength. Correct feeling: exact same count every length, turn happens without looking or guessing.

4. Вращение корпуса на спине (Body Rotation Drill) — плывёшь на спине, концентрируясь исключительно на вращении плечо-в-плечо, не на скорости гребка.
   How: take slow, deliberate strokes. On each entry, the shoulder of the entering arm should nearly touch the chin. The pulling arm uses the rotation as a lever.
   Common mistake: flat swimming with no rotation — all arm, no core. Correct feeling: hips and shoulders rotate as one unit, stroke feels powerful with less effort.

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

РАЗМИНКА всегда состоит из 3 элементов:
  1. Лёгкое плавание 200–400 м (выбор стиля)
  2. Нарастающая серия: 4×[25 или 50] м (первая половина легко, вторая в полсилы)
  3. Ноги с доской 2×[25 или 50] м

Шаблон строки упражнения:
▸ [N ×] [дистанция] м  [стиль / название]
❤️ Пульс: ~ХХ уд/10 сек ([название зоны — Recovery/Aerobic/Threshold/Speed/Maximum на русском])
⏱ Отдых: [X сек] или [нет]
📖 Как плыть: [2-3 предложения — темп, дыхание, положение тела]
💡 Зачем: [одна фраза]

━━━━━━━━━━━━━━━━━━━━━━━━
🎯 ТЕХНИКА · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

Шаблон строки упражнения:
▸ [N ×] [дистанция] м  [название упражнения]
💡 Зачем: [что исправляет или развивает]
📖 Как выполнять: [пошагово — положение тела, движение рук/ног, дыхание, типичные ошибки]
✅ Правильное ощущение: [как должно чувствоваться, если делаешь верно]
⏱ Отдых: [X сек]

━━━━━━━━━━━━━━━━━━━━━━━━
💪 ОСНОВНАЯ ЧАСТЬ · [X] м
━━━━━━━━━━━━━━━━━━━━━━━━

ОСНОВНАЯ ЧАСТЬ в тренировках ≥ 45 мин обязательно включает:
  - Минимум 1 серию НОГИ (с доской или без)
  - Минимум 1 серию РУКИ (с колобашкой)
  - Хотя бы 1 прогрессивную серию (нарастающая / пирамида / убывающий отдых)

Шаблон строки упражнения:
▸ [N ×] [дистанция] м  [стиль] [пометка: «ноги» / «руки» / «нарастание» / «пирамида» если применимо]
❤️ Пульс: ~ХХ уд/10 сек ([название зоны])
⏱ Отдых: [X сек]   ← или ⏱ Режим: стартуешь каждые [M:SS]  (для интервальных серий)
📖 Как плыть: [темп, ритм дыхания, где должно гореть]
💡 Зачем: [цель серии]
⏸ В паузе: [что делать во время отдыха — только если отдых ≥ 30 сек]

Если известны зоны темпа из профиля:
🎯 Целевой темп: [MM:SS]/100 м

Слова «цикл» и «отправление» НЕ использовать. Только «Отдых» или «Режим».

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

DISTANCE RULES (mandatory):
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
   If analytics state "MAXIMUM volume for next workout" — that limit must be strictly respected.
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
    usual_dist = user_data.get("usual_distance")
    usual_dist_line = (
        f"• Обычный объём пловца за тренировку: {usual_dist} м — "
        f"используй как базовый ориентир для первой тренировки (если нет истории)\n"
    ) if usual_dist else ""

    # Зоны темпа из личного рекорда
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

    # Дни тренировок и паттерн нагрузки
    days_map = {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт", "fri": "Пт", "sat": "Сб", "sun": "Вс"}
    weekday_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    training_days = user_data.get("training_days") or []
    if isinstance(training_days, str):
        import json as _json
        try:
            training_days = _json.loads(training_days)
        except Exception:
            training_days = []
    today_key = weekday_keys[datetime.now().weekday()]
    training_days_line = ""
    if training_days:
        days_ru = [days_map.get(d, d) for d in training_days]
        yesterday_key = weekday_keys[(weekday_keys.index(today_key) - 1) % 7]
        tomorrow_key = weekday_keys[(weekday_keys.index(today_key) + 1) % 7]
        yesterday_train = yesterday_key in training_days
        tomorrow_train = tomorrow_key in training_days
        load_hint = []
        if yesterday_train:
            load_hint.append("вчера была тренировка → не делай две тяжёлые подряд")
        if tomorrow_train:
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
        f"{usual_dist_line}"
        f"{pace_line}"
        f"{training_days_line}"
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
    workout_text = fix_section_distances(response.choices[0].message.content)

    valid, explanation, corrected = validate_workout(workout_text, user_data, history or [])
    if valid:
        return workout_text, explanation

    logging.warning("Валидация не прошла. Используем исправленную версию от валидатора.")
    if corrected:
        return fix_section_distances(corrected), explanation

    logging.error("Валидатор не вернул исправленную тренировку. Отправляем оригинал.")
    return workout_text, ""


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

            result.append(lines[i])       # открывающий разделитель
            header = lines[i + 1]
            header_idx = len(result)
            result.append(header)         # заголовок — заменим позже
            result.append(lines[i + 2])   # закрывающий разделитель
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

    # Обновляем итоговую строку ⏱ X м · ~Y мин
    total = _sum_sets(fixed.split('\n'))
    if total > 0:
        fixed = re.sub(r'(⏱\s*)\d[\d\s]*\s*м', f'\\g<1>{total} м', fixed)

    return fixed


def extract_distance(workout_text: str) -> int | None:
    total = _sum_sets(workout_text.split('\n'))
    if total > 0:
        return total
    # Запасной: заголовок ⏱ X м
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
