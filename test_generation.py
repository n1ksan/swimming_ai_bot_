"""
Тест генерации и валидации тренировки.
Запуск: python test_generation.py
"""
import json
import re
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ── Профиль для теста (меняй под нужный сценарий) ─────────────────────────
TEST_USER = {
    "level": "beginner",          # beginner / intermediate / advanced
    "goal": "fitness",            # fitness / weight_loss / competition / technique
    "pool_length": "25",
    "duration": "60",
    "sessions_per_week": "3",
    "strokes": ["freestyle"],
    "injuries": "",               # например "колено" или ""
    "best_100m_time": None,
}

# История последних тренировок (пустой список = первая тренировка)
TEST_HISTORY = [
    # {"completed": True, "distance_meters": 700, "perceived_effort": 6,
    #  "feedback": "", "workout_type": "выносливость", "date": "2026-04-21"},
]

SEP = "=" * 70


def _get_client():
    return OpenAI()


def _call_llm(system: str, user: str, max_tokens: int, temperature: float) -> str:
    client = _get_client()
    response = client.chat.completions.create(
        model="gpt-5.4-mini-2026-03-17",
        max_completion_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content


def run_test():
    from workout_generator import (
        SYSTEM_PROMPT,
        VALIDATOR_PROMPT,
        _build_history_context,
    )
    from collections import Counter

    completed = [w for w in TEST_HISTORY if w.get("completed")]
    workout_number = len(completed) + 1
    history_context = _build_history_context(TEST_HISTORY)

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

    level = level_map.get(TEST_USER["level"], "Новичок")
    goal = goal_map.get(TEST_USER["goal"], "Общая физическая форма")
    strokes = ", ".join(strokes_map.get(s, s) for s in TEST_USER.get("strokes", ["freestyle"]))
    injuries = TEST_USER.get("injuries") or "нет"
    pace = TEST_USER.get("best_100m_time")
    pace_line = f"• Личный темп на 100 м: {pace}\n" if pace else ""

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

    user_prompt = (
        f"ПРОФИЛЬ ПЛОВЦА:\n"
        f"• Уровень: {level}\n"
        f"• Цель: {goal}\n"
        f"• Бассейн: {TEST_USER['pool_length']} м\n"
        f"• Время на тренировку: {TEST_USER['duration']} мин\n"
        f"• Тренировок в неделю: {TEST_USER['sessions_per_week']}\n"
        f"• Предпочитаемые стили: {strokes}\n"
        f"• Травмы/ограничения: {injuries}\n"
        f"{pace_line}"
        f"• Номер тренировки: #{workout_number}"
        f"{history_context}\n\n"
        f"Составь тренировку типа {recommended}. "
        f"Строго соблюди лимит серий для уровня. "
        f"Все 4 секции (РАЗМИНКА, ТЕХНИКА, ОСНОВНАЯ ЧАСТЬ, ЗАМИНКА) обязательны. "
        f"Учти травмы при подборе упражнений."
    )

    # ── Шаг 1: генерация ──────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("ШАГ 1 — ГЕНЕРАЦИЯ (до валидации)")
    print(SEP)
    print("Генерирую тренировку...")

    raw_workout = _call_llm(SYSTEM_PROMPT, user_prompt, max_tokens=2048, temperature=0.7)

    print("\n" + raw_workout)

    # ── Шаг 2: валидация ──────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("ШАГ 2 — ВАЛИДАЦИЯ")
    print(SEP)

    level_label_map = {"beginner": "новичок", "intermediate": "средний", "advanced": "продвинутый"}
    level_label = level_label_map.get(TEST_USER["level"], "новичок")
    prev_distance = completed[0]["distance_meters"] if completed and completed[0].get("distance_meters") else None
    prev_line = f"Предыдущий объём: {prev_distance} м." if prev_distance else "Предыдущих тренировок нет."
    user_context = f"Уровень пловца: {level_label}. Травмы/ограничения: {injuries}. {prev_line}"

    validator_input = f"{user_context}\n\nТРЕНИРОВКА:\n{raw_workout}"
    raw_validator = _call_llm(VALIDATOR_PROMPT, validator_input, max_tokens=3000, temperature=0.1)

    raw_clean = re.sub(r"^```json\s*|^```\s*|\s*```$", "", raw_validator, flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw_clean)
    except json.JSONDecodeError:
        print("Ошибка парсинга JSON от валидатора:")
        print(raw_validator)
        return

    valid = data.get("valid", True)
    reason = data.get("reason", "")
    explanation = data.get("explanation", "")
    corrected = data.get("corrected_workout")

    print(f"valid     : {valid}")
    print(f"reason    : {reason or '—'}")
    print(f"explanation: {explanation or '—'}")

    # ── Шаг 3: итог ───────────────────────────────────────────────────────
    print(f"\n{SEP}")
    if valid:
        print("ИТОГ — тренировка прошла валидацию без изменений ✅")
        print(SEP)
    elif corrected:
        print("ИТОГ — валидатор нашёл нарушения и исправил тренировку ⚠️")
        print(SEP)
        print("\nИСПРАВЛЕННАЯ ТРЕНИРОВКА:")
        print(corrected)
    else:
        print("ИТОГ — валидатор нашёл нарушения, но не вернул исправленную версию ❌")
        print(SEP)


if __name__ == "__main__":
    run_test()
