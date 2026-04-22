import logging
import re
from datetime import datetime, timedelta

from telegram import BotCommand, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from database import (
    init_db,
    save_user_profile,
    get_user_profile,
    save_workout,
    get_workout_by_id,
    mark_workout_completed,
    get_workout_history,
    get_stats,
    get_week_workouts,
    update_user_field,
)
from workout_generator import generate_workout, extract_distance, extract_workout_type

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Состояния диалогов ─────────────────────────────────────────────────────
INTRO = 10
PROFILE_CHOICE, LEVEL, GOAL, POOL, DURATION, SESSIONS, STROKES, INJURIES = range(8)
LOG_EFFORT, LOG_COMPLETION, LOG_COMMENT = range(3)
PACE_INPUT = 0
REMINDER_MENU = 0

# ── Метки ──────────────────────────────────────────────────────────────────
LEVEL_LABELS = {
    "beginner": "🌱 Новичок",
    "intermediate": "🏊 Средний уровень",
    "advanced": "🏆 Продвинутый",
}
GOAL_LABELS = {
    "fitness": "💪 Физическая форма",
    "weight_loss": "🔥 Снижение веса",
    "competition": "🥇 Соревнования",
    "technique": "🎯 Улучшение техники",
}
STROKES_LABELS = {
    "freestyle": "Вольный стиль",
    "backstroke": "На спине",
    "breaststroke": "Брасс",
    "butterfly": "Баттерфляй",
    "all": "Все стили",
}
WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
WEEKDAY_FULL = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
WORKOUT_TYPE_EMOJI = {
    "выносливость": "🏊",
    "скорость": "⚡",
    "техника": "🎯",
    "восстановление": "💆",
}


# ── Вспомогательные функции ────────────────────────────────────────────────

import html as _html_module


def _workout_to_html(text: str) -> list[str]:
    """Возвращает список самодостаточных HTML-блоков (ни один тег не разрезается)."""
    text = re.sub(r'━{4,}', '━━━━━━━━', text)

    lines = text.split('\n')
    blocks: list[str] = []
    plain: list[str] = []
    i = 0

    def md_to_html(line: str) -> str:
        line = _html_module.escape(line)
        line = re.sub(r'\*([^*\n]+)\*', r'<b>\1</b>', line)
        line = re.sub(r'_([^_\n]+)_', r'<i>\1</i>', line)
        return line

    def is_sep(line: str) -> bool:
        s = line.strip()
        return bool(s) and all(c == '━' for c in s)

    def flush_plain() -> None:
        stripped = '\n'.join(plain).strip()
        if stripped:
            blocks.append(stripped)
        plain.clear()

    while i < len(lines):
        # Паттерн секции: разделитель + заголовок + разделитель
        if (is_sep(lines[i])
                and i + 2 < len(lines)
                and lines[i + 1].strip()
                and not is_sep(lines[i + 1])
                and is_sep(lines[i + 2])):

            flush_plain()
            title = lines[i + 1]
            i += 3

            content = []
            while i < len(lines) and not is_sep(lines[i]):
                content.append(md_to_html(lines[i]))
                i += 1

            # Убираем крайние пустые строки и внутренние двойные пробелы —
            # иначе \n\n внутри blockquote разрежет блок при отправке
            while content and not content[0].strip():
                content.pop(0)
            while content and not content[-1].strip():
                content.pop()
            content = [ln for ln in content if ln.strip()]

            body = '<b>' + md_to_html(title) + '</b>'
            if content:
                body += '\n<blockquote expandable>' + '\n'.join(content) + '</blockquote>'
            blocks.append(body)
        else:
            plain.append(md_to_html(lines[i]))
            i += 1

    flush_plain()
    return blocks


async def _send_html_text(message, blocks: list[str]) -> None:
    """Отправляет список HTML-блоков сообщениями ≤ 4000 символов.
    Блоки не разрезаются — каждый блок попадает в один чанк целиком."""
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        block_len = len(block) + 2  # +2 за разделитель \n\n
        if current_len + block_len > 4000 and current:
            chunks.append('\n\n'.join(current))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += block_len

    if current:
        chunks.append('\n\n'.join(current))

    for chunk in chunks:
        await message.reply_text(chunk, parse_mode="HTML")


# ── Общий помощник генерации ───────────────────────────────────────────────

async def _generate_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> None:
    if context.user_data.get("is_generating"):
        await update.effective_message.reply_text("⏳ Тренировка уже генерируется, подожди немного...")
        return


    context.user_data["is_generating"] = True
    try:
        history = get_workout_history(user_id, limit=20)
        try:
            workout_text, explanation = generate_workout(context.user_data, history)
        except Exception as e:
            logger.error(f"Ошибка генерации для пользователя {user_id}: {e}")
            await update.effective_message.reply_text(
                "😔 Ошибка генерации тренировки. Проверь OPENAI_API_KEY и попробуй снова.",
            )
            return

        workout_type = extract_workout_type(workout_text)
        workout_id = save_workout(user_id, workout_text, workout_type)
        context.user_data["last_workout_id"] = workout_id
        context.user_data["last_workout_text"] = workout_text

        keyboard = [
            [InlineKeyboardButton("✅ Отметить как выполненную", callback_data="log_workout")],
            [InlineKeyboardButton("🔄 Другая тренировка", callback_data="new_workout")],
            [InlineKeyboardButton("📤 Сохранить тренировку", callback_data="save_workout")],
            [InlineKeyboardButton("📋 Изменить профиль", callback_data="restart")],
        ]
        await _send_html_text(update.effective_message, _workout_to_html(workout_text))
        if explanation:
            await update.effective_message.reply_text(
                f"💭 *Почему именно эта тренировка:*\n{explanation}",
                parse_mode="Markdown",
            )
        await update.effective_message.reply_text(
            "Как прошла тренировка?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    finally:
        context.user_data["is_generating"] = False


def _finalize_log(
    workout_id,
    effort: int,
    feedback: str,
    completion_rate: str = "full",
    actual_distance: int = None,
) -> None:
    if not workout_id:
        return
    w = get_workout_by_id(workout_id)
    distance = actual_distance
    if distance is None and w:
        distance = w.get("distance_meters") or extract_distance(w["workout_text"])
    mark_workout_completed(workout_id, effort, feedback, distance, completion_rate, actual_distance)


# ── /start ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)

    if profile:
        context.user_data.update(profile)
        level_label = LEVEL_LABELS.get(profile["level"], profile["level"])
        goal_label = GOAL_LABELS.get(profile["goal"], profile["goal"])
        keyboard = [
            [InlineKeyboardButton("⚡ Использовать сохранённый профиль", callback_data="use_profile")],
            [InlineKeyboardButton("✏️ Изменить профиль", callback_data="change_profile")],
        ]
        await update.message.reply_text(
            f"👋 С возвращением!\n\n"
            f"Твой профиль:\n"
            f"• Уровень: {level_label}\n"
            f"• Цель: {goal_label}\n"
            f"• Бассейн: {profile['pool_length']} м\n"
            f"• Время: {profile['duration']} мин\n\n"
            f"Сгенерировать тренировку с этим профилем?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return PROFILE_CHOICE

    return await _start_onboarding(update, context)


async def _start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    return await _show_intro(update, context)


async def _show_intro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [[InlineKeyboardButton("▶️ Начать", callback_data="intro_start")]]
    await update.effective_message.reply_text(
        "🏊 *ПЕРСОНАЛЬНЫЙ ТРЕНЕР ПО ПЛАВАНИЮ*\n\n"
        "Составляю тренировки на основе твоего уровня, цели и истории. "
        "Каждая тренировка адаптируется — чем больше тренируешься, тем точнее план.\n\n"
        "Займёт 1 минуту — отвечай на вопросы и сразу получишь тренировку.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return INTRO


async def _intro_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🌱 Новичок", callback_data="beginner")],
        [InlineKeyboardButton("🏊 Средний уровень", callback_data="intermediate")],
        [InlineKeyboardButton("🏆 Продвинутый", callback_data="advanced")],
    ]
    await query.edit_message_text(
        "🏊 *Какой у тебя уровень плавания?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return LEVEL


async def profile_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "use_profile":
        await query.edit_message_text(
            "⚙️ *Генерирую тренировку с учётом истории...* 🏊",
            parse_mode="Markdown",
        )
        await _generate_and_send(update, context, query.from_user.id)
        return ConversationHandler.END

    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🌱 Новичок", callback_data="beginner")],
        [InlineKeyboardButton("🏊 Средний уровень", callback_data="intermediate")],
        [InlineKeyboardButton("🏆 Продвинутый", callback_data="advanced")],
    ]
    await query.edit_message_text(
        "🏊 *Какой у тебя уровень плавания?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return LEVEL


# ── Шаги регистрации ───────────────────────────────────────────────────────

async def level_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["level"] = query.data
    keyboard = [
        [InlineKeyboardButton("💪 Физическая форма", callback_data="fitness")],
        [InlineKeyboardButton("🔥 Снижение веса", callback_data="weight_loss")],
        [InlineKeyboardButton("🥇 Соревнования", callback_data="competition")],
        [InlineKeyboardButton("🎯 Улучшение техники", callback_data="technique")],
    ]
    await query.edit_message_text(
        "🎯 *Какова твоя цель?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return GOAL


async def goal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["goal"] = query.data
    keyboard = [
        [InlineKeyboardButton("📏 25 м", callback_data="25")],
        [InlineKeyboardButton("📏 50 м", callback_data="50")],
    ]
    await query.edit_message_text(
        "📏 *Длина твоего бассейна?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return POOL


async def pool_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["pool_length"] = query.data
    keyboard = [
        [
            InlineKeyboardButton("⏱ 30 мин", callback_data="30"),
            InlineKeyboardButton("⏱ 45 мин", callback_data="45"),
        ],
        [
            InlineKeyboardButton("⏱ 60 мин", callback_data="60"),
            InlineKeyboardButton("⏱ 90 мин", callback_data="90"),
        ],
    ]
    await query.edit_message_text(
        "⏱ *Сколько времени на тренировку?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return DURATION


async def duration_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["duration"] = query.data
    keyboard = [
        [
            InlineKeyboardButton("2×", callback_data="2"),
            InlineKeyboardButton("3×", callback_data="3"),
        ],
        [
            InlineKeyboardButton("4×", callback_data="4"),
            InlineKeyboardButton("5+×", callback_data="5"),
        ],
    ]
    await query.edit_message_text(
        "📅 *Сколько тренировок в неделю?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SESSIONS


async def sessions_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["sessions_per_week"] = query.data
    context.user_data["strokes"] = []
    keyboard = [
        [InlineKeyboardButton("🏊 Вольный стиль", callback_data="freestyle")],
        [InlineKeyboardButton("🔄 На спине", callback_data="backstroke")],
        [InlineKeyboardButton("🐸 Брасс", callback_data="breaststroke")],
        [InlineKeyboardButton("🦋 Баттерфляй", callback_data="butterfly")],
        [InlineKeyboardButton("✅ Все стили", callback_data="all")],
        [InlineKeyboardButton("➡️ Готово", callback_data="done")],
    ]
    await query.edit_message_text(
        "🏊 *Какие стили плавания предпочитаешь?*\n\nМожно выбрать несколько.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return STROKES


async def strokes_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "done":
        if not context.user_data.get("strokes"):
            context.user_data["strokes"] = ["freestyle"]
        await query.edit_message_text(
            "🩹 *Есть травмы или ограничения?*\n\nНапиши текстом или отправь «нет».",
            parse_mode="Markdown",
        )
        return INJURIES

    if query.data == "all":
        context.user_data["strokes"] = ["all"]
    else:
        strokes = context.user_data.get("strokes", [])
        if "all" in strokes:
            strokes = []
        if query.data in strokes:
            strokes.remove(query.data)
        else:
            strokes.append(query.data)
        context.user_data["strokes"] = strokes

    selected = context.user_data.get("strokes", [])
    selected_text = ", ".join(STROKES_LABELS.get(s, s) for s in selected) or "ничего"

    keyboard = [
        [InlineKeyboardButton("🏊 Вольный стиль", callback_data="freestyle")],
        [InlineKeyboardButton("🔄 На спине", callback_data="backstroke")],
        [InlineKeyboardButton("🐸 Брасс", callback_data="breaststroke")],
        [InlineKeyboardButton("🦋 Баттерфляй", callback_data="butterfly")],
        [InlineKeyboardButton("✅ Все стили", callback_data="all")],
        [InlineKeyboardButton("➡️ Готово", callback_data="done")],
    ]
    await query.edit_message_text(
        f"🏊 *Какие стили предпочитаешь?*\n\nВыбрано: _{selected_text}_\n\nНажми «Готово» когда закончишь.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return STROKES


async def injuries_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    context.user_data["injuries"] = "" if text.lower() == "нет" else text

    save_user_profile(user_id, context.user_data)

    await update.message.reply_text(
        "⚙️ *Генерирую твою персональную тренировку...* 🏊",
        parse_mode="Markdown",
    )
    await _generate_and_send(update, context, user_id)
    return ConversationHandler.END


# ── Действия после тренировки ──────────────────────────────────────────────

async def post_workout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "new_workout":
        await query.answer()
        await query.edit_message_text(
            "⚙️ *Генерирую новую тренировку...* 🏊",
            parse_mode="Markdown",
        )
        await _generate_and_send(update, context, user_id)

    elif query.data == "save_workout":
        workout_text = context.user_data.get("last_workout_text", "")
        if workout_text:
            await query.answer("📤 Тренировка отправлена в чат!", show_alert=True)
            await _send_html_text(query.message, _workout_to_html(workout_text))
        else:
            await query.answer("Тренировка не найдена. Сгенерируй новую.", show_alert=True)

    elif query.data == "restart":
        await query.answer()
        await query.edit_message_text(
            "Напиши /start чтобы изменить профиль и получить новую тренировку."
        )



# ── Диалог записи тренировки ───────────────────────────────────────────────

async def log_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data="effort_1"),
            InlineKeyboardButton("2", callback_data="effort_2"),
            InlineKeyboardButton("3", callback_data="effort_3"),
            InlineKeyboardButton("4", callback_data="effort_4"),
            InlineKeyboardButton("5", callback_data="effort_5"),
        ],
        [
            InlineKeyboardButton("6", callback_data="effort_6"),
            InlineKeyboardButton("7", callback_data="effort_7"),
            InlineKeyboardButton("8", callback_data="effort_8"),
            InlineKeyboardButton("9", callback_data="effort_9"),
            InlineKeyboardButton("10", callback_data="effort_10"),
        ],
    ]
    await query.edit_message_text(
        "💪 *Оцени нагрузку тренировки:*\n\n"
        "1-4 — лёгкая\n"
        "5-7 — оптимальная\n"
        "8-10 — очень тяжёлая\n\n"
        "Это поможет тренеру правильно строить следующие тренировки.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return LOG_EFFORT


async def log_effort_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    effort = int(query.data.split("_")[1])
    context.user_data["log_effort"] = effort

    keyboard = [
        [
            InlineKeyboardButton("✅ Полностью", callback_data="completion_full"),
            InlineKeyboardButton("✂️ Сократил", callback_data="completion_partial"),
        ],
        [InlineKeyboardButton("❌ Не смог доплыть", callback_data="completion_failed")],
    ]
    await query.edit_message_text(
        f"Нагрузка: *{effort}/10* ✅\n\n"
        "🏁 *Выполнил тренировку полностью?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return LOG_COMPLETION


async def log_completion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    completion = query.data.split("_")[1]
    context.user_data["log_completion"] = completion

    keyboard = [[InlineKeyboardButton("⏭ Пропустить", callback_data="log_skip")]]
    await query.edit_message_text(
        "💬 *Добавь короткий комментарий* (необязательно):\n"
        "_Например: «устал к концу», «болело плечо»_",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return LOG_COMMENT


async def log_comment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    feedback = update.message.text.strip()
    effort = context.user_data.get("log_effort", 5)
    workout_id = context.user_data.get("last_workout_id")
    completion_rate = context.user_data.get("log_completion", "full")

    _finalize_log(workout_id, effort, feedback, completion_rate)

    await update.message.reply_text(
        f"✅ *Тренировка записана!*\n\n"
        f"Нагрузка: {effort}/10\n"
        f"Комментарий: _{feedback}_\n\n"
        f"Тренер учтёт это при следующей тренировке 📈\n\n"
        f"• /newworkout — следующая тренировка\n"
        f"• /history — история тренировок",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def log_skip_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    effort = context.user_data.get("log_effort", 5)
    workout_id = context.user_data.get("last_workout_id")
    completion_rate = context.user_data.get("log_completion", "full")

    _finalize_log(workout_id, effort, "", completion_rate)

    await query.edit_message_text(
        f"✅ *Тренировка записана!* Нагрузка: {effort}/10\n\n"
        f"• /newworkout — следующая тренировка\n"
        f"• /history — история тренировок",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── /newworkout ────────────────────────────────────────────────────────────

async def new_workout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)
    if not profile:
        await update.message.reply_text(
            "Профиль не найден. Используй /start для настройки."
        )
        return
    context.user_data.update(profile)
    await update.message.reply_text(
        "⚙️ *Генерирую тренировку с учётом истории...* 🏊",
        parse_mode="Markdown",
    )
    await _generate_and_send(update, context, user_id)


# ── /history ───────────────────────────────────────────────────────────────

async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    history = get_workout_history(user_id, limit=10)

    if not history:
        await update.message.reply_text(
            "У тебя пока нет тренировок. Используй /start или /newworkout."
        )
        return

    completed = [w for w in history if w["completed"]]
    lines = ["📊 *ИСТОРИЯ ТРЕНИРОВОК* (последние 10)\n"]

    for w in history:
        status = "✅" if w["completed"] else "⏳"
        line = f"{status} *{w['date']}*"
        if w["distance_meters"]:
            line += f" — {w['distance_meters']} м"
        if w["perceived_effort"]:
            line += f" | 💪 {w['perceived_effort']}/10"
        lines.append(line)
        if w["feedback"]:
            lines.append(f"   _{w['feedback']}_")

    if completed:
        lines.append("\n📈 *Статистика выполненных:*")
        efforts = [w["perceived_effort"] for w in completed if w["perceived_effort"]]
        distances = [w["distance_meters"] for w in completed if w["distance_meters"]]
        if distances:
            lines.append(f"• Средний объём: {sum(distances) // len(distances)} м")
        if efforts:
            lines.append(f"• Средняя нагрузка: {sum(efforts) / len(efforts):.1f}/10")
        lines.append(f"• Выполнено: {len(completed)}/{len(history)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /stats ─────────────────────────────────────────────────────────────────

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    stats = get_stats(user_id)

    if stats["total_workouts"] == 0:
        await update.message.reply_text(
            "У тебя пока нет выполненных тренировок.\n\nИспользуй /newworkout чтобы начать."
        )
        return

    last_8 = list(stats["last_8"])
    last_8.reverse()
    progression = " → ".join(
        f"{d}м{'(в)' if t == 'восстановление' else ''}"
        for d, t in last_8 if d
    ) or "—"

    trend_text = f" ({stats['effort_trend']})" if stats["effort_trend"] else ""

    cur = stats["distance_30d"]
    prev = stats["prev_distance_30d"]
    if prev > 0:
        diff = round((cur - prev) / prev * 100)
        if diff > 0:
            volume_trend = f"📈 Объём вырос на {diff}%"
        elif diff < 0:
            volume_trend = f"📉 Объём снизился на {abs(diff)}%"
        else:
            volume_trend = "➡️ Объём стабилен"
    elif cur > 0:
        volume_trend = "📈 Объём вырос на 100%"
    else:
        volume_trend = "➡️ Объём стабилен"

    partial_line = f"• Частично выполнено: {stats['partial_count']}\n" if stats["partial_count"] else ""

    text = (
        f"📈 *ТВОЙ ПРОГРЕСС*\n\n"
        f"*За всё время:*\n"
        f"• Тренировок выполнено: {stats['total_workouts']}\n"
        f"{partial_line}"
        f"• Общий объём: {stats['total_distance']} м "
        f"({stats['total_distance'] // 1000} км)\n"
        f"• Средняя нагрузка: {stats['avg_effort_all']}/10\n\n"
        f"*За последние 30 дней:*\n"
        f"• Тренировок: {stats['workouts_30d']}\n"
        f"• Объём: {stats['distance_30d']} м\n"
        f"• Средняя нагрузка: {stats['avg_effort_30d']}/10{trend_text}\n"
        f"• {volume_trend}\n\n"
        f"*Рекорды:*\n"
        f"• Максимальный объём: {stats['best_distance']} м\n"
        f"• Серия без пропусков: {stats['streak']} дн.\n\n"
        f"*Прогрессия объёма (последние 8):*\n"
        f"{progression}\n"
        f"_(в) — восстановительная_"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


# ── /week ──────────────────────────────────────────────────────────────────

async def week_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    workouts = get_week_workouts(user_id)

    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())

    workout_by_day: dict = {}
    for w in workouts:
        workout_by_day.setdefault(w["weekday"], []).append(w)

    lines = ["📅 *ПЛАН НА ЭТУ НЕДЕЛЮ*\n"]
    total_distance = 0

    for day_idx in range(7):
        day_date = monday + timedelta(days=day_idx)
        day_name = WEEKDAY_FULL[day_idx]

        if day_idx in workout_by_day:
            for w in workout_by_day[day_idx]:
                emoji = WORKOUT_TYPE_EMOJI.get(w["workout_type"], "🏊")
                status = "✅" if w["completed"] else "⏳"
                dist = f" ({w['distance_meters']} м)" if w["distance_meters"] else ""
                type_label = w["workout_type"].capitalize()
                today_mark = " ← сегодня" if day_date == today else ""
                if day_date == today:
                    lines.append(f"{status} *{day_name}* — {emoji} {type_label}{dist}{today_mark}")
                else:
                    lines.append(f"{status} {day_name} — {emoji} {type_label}{dist}")
                if w["completed"] and w["distance_meters"]:
                    total_distance += w["distance_meters"]
        elif day_date == today:
            lines.append(f"📌 *{day_name}* — сегодня, /newworkout")
        elif day_date > today:
            lines.append(f"🔒 {day_name}")
        else:
            lines.append(f"— {day_name} (пропущено)")

    if total_distance:
        lines.append(f"\n💧 Объём за неделю: *{total_distance} м*")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /profile ───────────────────────────────────────────────────────────────

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)

    if not profile:
        await update.message.reply_text(
            "Профиль не найден. Используй /start для настройки."
        )
        return

    level = LEVEL_LABELS.get(profile["level"], profile["level"])
    goal = GOAL_LABELS.get(profile["goal"], profile["goal"])
    strokes = ", ".join(STROKES_LABELS.get(s, s) for s in (profile.get("strokes") or []))
    pace = profile.get("best_100m_time")
    pace_line = f"• Темп на 100 м: {pace}\n" if pace else ""

    await update.message.reply_text(
        f"👤 *Твой профиль:*\n\n"
        f"• Уровень: {level}\n"
        f"• Цель: {goal}\n"
        f"• Бассейн: {profile['pool_length']} м\n"
        f"• Время: {profile['duration']} мин\n"
        f"• Тренировок/нед: {profile['sessions_per_week']}\n"
        f"• Стили: {strokes or '—'}\n"
        f"• Ограничения: {profile['injuries'] or 'нет'}\n"
        f"{pace_line}\n"
        f"Используй /start чтобы изменить профиль.",
        parse_mode="Markdown",
    )


# ── /goal ──────────────────────────────────────────────────────────────────

async def goal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)
    if not profile:
        await update.message.reply_text("Профиль не найден. Используй /start.")
        return

    current_label = GOAL_LABELS.get(profile["goal"], profile["goal"])
    keyboard = [
        [InlineKeyboardButton("💪 Физическая форма", callback_data="change_goal_fitness")],
        [InlineKeyboardButton("🔥 Снижение веса", callback_data="change_goal_weight_loss")],
        [InlineKeyboardButton("🥇 Соревнования", callback_data="change_goal_competition")],
        [InlineKeyboardButton("🎯 Улучшение техники", callback_data="change_goal_technique")],
        [InlineKeyboardButton("✖️ Отмена", callback_data="change_goal_cancel")],
    ]
    await update.message.reply_text(
        f"🎯 *Текущая цель:* {current_label}\n\nВыбери новую цель:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def goal_change_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "change_goal_cancel":
        await query.edit_message_text("Цель не изменена.")
        return

    new_goal = query.data.replace("change_goal_", "")
    user_id = query.from_user.id
    update_user_field(user_id, "goal", new_goal)
    if context.user_data:
        context.user_data["goal"] = new_goal

    label = GOAL_LABELS.get(new_goal, new_goal)
    await query.edit_message_text(
        f"✅ Цель изменена на *{label}*!\n\n"
        f"Следующая тренировка будет составлена под новую цель.\n\n"
        f"/newworkout — получить тренировку",
        parse_mode="Markdown",
    )


# ── /setpace ───────────────────────────────────────────────────────────────

async def setpace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    profile = get_user_profile(user_id)
    current = profile.get("best_100m_time") if profile else None
    current_text = f"Текущий темп: *{current}* на 100 м\n\n" if current else ""

    keyboard = [[InlineKeyboardButton("✖️ Отмена", callback_data="pace_cancel")]]
    await update.message.reply_text(
        f"{current_text}"
        "Введи своё время на 100 м вольным стилем.\n"
        "Формат: *1:45* или *2:10*\n\n"
        "_Тренер будет рассчитывать интервалы под твой темп._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return PACE_INPUT


async def pace_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if not re.match(r"^\d{1,2}:\d{2}$", text):
        await update.message.reply_text(
            "Неверный формат. Введи время как *1:45* или *2:00*",
            parse_mode="Markdown",
        )
        return PACE_INPUT

    user_id = update.effective_user.id
    update_user_field(user_id, "best_100m_time", text)
    context.user_data["best_100m_time"] = text

    await update.message.reply_text(
        f"✅ Темп сохранён: *{text}* на 100 м\n\n"
        "Тренер учтёт его при составлении следующих тренировок.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def pace_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Темп не изменён.")
    return ConversationHandler.END


# ── /reminders ─────────────────────────────────────────────────────────────

_MONTHS_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


async def _show_reminders_menu(msg, user_id: int, edit: bool = False) -> None:
    profile = get_user_profile(user_id)
    enabled = profile.get("reminders_enabled", 0) if profile else 0

    toggle_text = "❌ Выключить напоминания" if enabled else "✅ Включить напоминания"
    status = "✅ Включены" if enabled else "❌ Выключены"

    last_sent_line = ""
    last_sent_raw = profile.get("last_reminder_sent") if profile else None
    if last_sent_raw:
        try:
            dt = datetime.fromisoformat(last_sent_raw)
            last_sent_line = f"\nПоследнее: {dt.day} {_MONTHS_RU[dt.month - 1]} в {dt.strftime('%H:%M')}"
        except ValueError:
            pass

    keyboard = [
        [InlineKeyboardButton(toggle_text, callback_data="reminder_toggle")],
        [InlineKeyboardButton("✖️ Закрыть", callback_data="reminder_close")],
    ]
    text = (
        f"🔔 *Напоминания о тренировках*\n\n"
        f"Статус: {status}\n"
        f"Время: 9:00 утра каждый день"
        f"{last_sent_line}"
    )
    markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await msg.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await msg.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def reminders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _show_reminders_menu(update.message, update.effective_user.id)
    return REMINDER_MENU


async def reminder_toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    profile = get_user_profile(user_id)
    current = profile.get("reminders_enabled", 0) if profile else 0
    update_user_field(user_id, "reminders_enabled", 0 if current else 1)
    await _show_reminders_menu(query.message, user_id, edit=True)
    return REMINDER_MENU


async def reminder_close_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("🔔 Настройки напоминаний сохранены.")
    return ConversationHandler.END


# ── /help ──────────────────────────────────────────────────────────────────

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🏊 *ТРЕНЕР ПО ПЛАВАНИЮ — КОМАНДЫ*\n\n"
        "/newworkout — получить тренировку\n"
        "/week — план на эту неделю\n"
        "/stats — мой прогресс\n"
        "/history — история тренировок\n"
        "/profile — мой профиль\n"
        "/goal — сменить цель\n"
        "/setpace — указать темп на 100 м\n"
        "/reminders — настроить напоминания\n"
        "/start — изменить профиль полностью\n"
        "/cancel — отменить текущий диалог",
        parse_mode="Markdown",
    )


# ── /cancel ────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "Диалог отменён. Напиши /start чтобы начать заново."
    )
    return ConversationHandler.END


# ── Обработчик ошибок ──────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Необработанная ошибка", exc_info=context.error)


# ── Регистрация меню команд ────────────────────────────────────────────────

async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("newworkout", "Получить тренировку"),
        BotCommand("week", "План на эту неделю"),
        BotCommand("stats", "Мой прогресс"),
        BotCommand("history", "История тренировок"),
        BotCommand("profile", "Мой профиль"),
        BotCommand("goal", "Сменить цель"),
        BotCommand("setpace", "Указать темп на 100 м"),
        BotCommand("reminders", "Настроить напоминания"),
        BotCommand("start", "Изменить профиль"),
        BotCommand("help", "Справка"),
    ])


# ── Сборка приложения ──────────────────────────────────────────────────────

def build_application(token: str) -> Application:
    init_db()
    app = Application.builder().token(token).post_init(_post_init).build()

    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            INTRO: [
                CallbackQueryHandler(_intro_start_handler, pattern="^intro_start$")
            ],
            PROFILE_CHOICE: [
                CallbackQueryHandler(
                    profile_choice_handler,
                    pattern="^(use_profile|change_profile)$",
                )
            ],
            LEVEL: [
                CallbackQueryHandler(
                    level_handler,
                    pattern="^(beginner|intermediate|advanced)$",
                )
            ],
            GOAL: [
                CallbackQueryHandler(
                    goal_handler,
                    pattern="^(fitness|weight_loss|competition|technique)$",
                )
            ],
            POOL: [CallbackQueryHandler(pool_handler, pattern="^(25|50)$")],
            DURATION: [CallbackQueryHandler(duration_handler, pattern="^(30|45|60|90)$")],
            SESSIONS: [CallbackQueryHandler(sessions_handler, pattern="^[2-9]$")],
            STROKES: [CallbackQueryHandler(strokes_handler)],
            INJURIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, injuries_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    log_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(log_start, pattern="^log_workout$")],
        states={
            LOG_EFFORT: [
                CallbackQueryHandler(log_effort_handler, pattern=r"^effort_\d+$")
            ],
            LOG_COMPLETION: [
                CallbackQueryHandler(
                    log_completion_handler,
                    pattern="^completion_(full|partial|failed)$",
                )
            ],
            LOG_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, log_comment_handler),
                CallbackQueryHandler(log_skip_handler, pattern="^log_skip$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    setpace_conv = ConversationHandler(
        entry_points=[CommandHandler("setpace", setpace_cmd)],
        states={
            PACE_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pace_input_handler),
                CallbackQueryHandler(pace_cancel_handler, pattern="^pace_cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    reminders_conv = ConversationHandler(
        entry_points=[CommandHandler("reminders", reminders_cmd)],
        states={
            REMINDER_MENU: [
                CallbackQueryHandler(reminder_toggle_handler, pattern="^reminder_toggle$"),
                CallbackQueryHandler(reminder_close_handler, pattern="^reminder_close$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(setup_conv)
    app.add_handler(log_conv)
    app.add_handler(setpace_conv)
    app.add_handler(reminders_conv)
    app.add_handler(CallbackQueryHandler(goal_change_callback, pattern="^change_goal_"))
    app.add_handler(
        CallbackQueryHandler(
            post_workout_handler,
            pattern="^(new_workout|restart|save_workout)$",
        )
    )
    app.add_handler(CommandHandler("newworkout", new_workout_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("week", week_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("goal", goal_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_error_handler(error_handler)

    return app
