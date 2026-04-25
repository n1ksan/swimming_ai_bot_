import os
from dataclasses import dataclass


@dataclass
class Config:
    telegram_token: str
    openai_api_key: str
    webapp_url: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("Не задана переменная окружения TELEGRAM_BOT_TOKEN")

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Не задана переменная окружения OPENAI_API_KEY")

        webapp_url = os.environ.get("WEBAPP_URL", "").strip()

        return cls(telegram_token=token, openai_api_key=api_key, webapp_url=webapp_url)
