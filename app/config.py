"""Environment-backed runtime configuration."""

import os
import re
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

_TELEGRAM_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    telegram_bot_token: str
    telegram_webhook_secret: str

    @classmethod
    def from_env(cls) -> "Settings":
        secret = _required("TELEGRAM_WEBHOOK_SECRET")
        if not _TELEGRAM_SECRET_PATTERN.fullmatch(secret):
            raise RuntimeError(
                "TELEGRAM_WEBHOOK_SECRET must contain 1-256 letters, digits, "
                "underscores, or hyphens"
            )
        return cls(
            openai_api_key=_required("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6").strip()
            or "gpt-5.6",
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_webhook_secret=secret,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
