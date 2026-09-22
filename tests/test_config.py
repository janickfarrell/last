import pytest

from config import load_settings
from telegram_sender import _telegram_url


def test_telegram_is_required_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_OPTIONAL", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        load_settings()


def test_one_shot_settings_allow_missing_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_OPTIONAL", "1")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    settings = load_settings()
    assert settings.telegram_bot_token == ""
    assert settings.admin_chat_id == 0


def test_telegram_url_has_no_brace_markers() -> None:
    url = _telegram_url("token", "sendMessage")
    assert url == "https://api.telegram.org/bottoken/sendMessage"
    assert "{{" not in url and "}}" not in url
