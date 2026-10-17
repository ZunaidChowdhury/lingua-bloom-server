import pytest

from app.core.config import Settings, load_settings


def _build() -> Settings:
    return Settings(
        groq_api_key="test-key",
        database_url="postgresql://user:pass@host:6543/postgres",
        _env_file=None,
    )


def test_documented_defaults() -> None:
    settings = _build()
    assert settings.groq_model == "llama-3.1-8b-instant"
    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.log_level == "INFO"
    assert settings.admin_key is None
    assert settings.llm_timeout_s == 1.5
    assert settings.progress_window == 5
    assert settings.progress_required_correct == 4
    assert settings.progress_min_distinct_skills == 3
    assert settings.hint_after_misses == 2
    assert settings.reveal_after_misses == 3
    assert settings.max_learning_streak == 3
    assert settings.checkin_every_n_turns == 8
    assert settings.context_turns == 6
    assert settings.max_input_chars == 200
    assert settings.max_reply_chars == 240
    assert settings.session_ttl_days == 30


def test_missing_required_variable_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        load_settings(_env_file=None)
    message = str(exit_info.value)
    assert "GROQ_API_KEY" in message
    assert "DATABASE_URL" in message
