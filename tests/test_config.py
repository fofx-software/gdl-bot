import pytest

from app.config import Settings


def test_settings_load_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "OPENAI_API_KEY": "openai-key",
        "OPENAI_MODEL": "gpt-test",
        "TELEGRAM_BOT_TOKEN": "telegram-token",
        "TELEGRAM_WEBHOOK_SECRET": "valid_secret-123",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    settings = Settings.from_env()

    assert settings.openai_model == "gpt-test"
    assert settings.telegram_bot_token == "telegram-token"


def test_settings_reject_invalid_telegram_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "invalid secret")

    with pytest.raises(RuntimeError, match="1-256"):
        Settings.from_env()
