import logging
import os
import threading
from datetime import time as dtime
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from telegram.ext import ContextTypes

from config import Config
from bot import build_application
from database import get_users_for_reminder, update_reminder_sent

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_logs_dir = Path(__file__).parent / "logs"
_logs_dir.mkdir(exist_ok=True)
_reminder_file_handler = logging.FileHandler(_logs_dir / "reminders.log", encoding="utf-8")
_reminder_file_handler.setLevel(logging.INFO)
_reminder_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
_reminder_logger = logging.getLogger("reminders")
_reminder_logger.addHandler(_reminder_file_handler)


async def _send_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_ids = get_users_for_reminder()
    for user_id in user_ids:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🏊 *Не забудь про тренировку сегодня!*\n\n"
                    "/newworkout — получить тренировку"
                ),
                parse_mode="Markdown",
            )
            update_reminder_sent(user_id)
            _reminder_logger.info(f"Напоминание отправлено пользователю {user_id}")
        except Exception as e:
            logger.warning(f"Не удалось отправить напоминание пользователю {user_id}: {e}")
            _reminder_logger.error(f"Ошибка отправки напоминания пользователю {user_id}: {e}")


def _run_api(port: int) -> None:
    uvicorn.run("api:app", host="0.0.0.0", port=port, log_level="warning")


def main() -> None:
    cfg = Config.from_env()

    port = int(os.environ.get("PORT", 8000))
    api_thread = threading.Thread(target=_run_api, args=(port,), daemon=True)
    api_thread.start()
    logger.info(f"API запущен на порту {port}")

    app = build_application(cfg.telegram_token, webapp_url=cfg.webapp_url)

    app.job_queue.run_daily(
        _send_reminders,
        time=dtime(hour=9, minute=0),
    )

    logger.info("Бот запущен. Нажми Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
