"""Application settings loaded from the environment."""

from functools import lru_cache

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration read from the environment or the local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    groq_api_key: str
    database_url: str

    groq_model: str = "llama-3.1-8b-instant"
    frontend_origin: str = "http://localhost:3000"
    log_level: str = "INFO"
    admin_key: str | None = None

    llm_timeout_s: float = 1.5
    progress_window: int = 5
    progress_required_correct: int = 4
    progress_min_distinct_skills: int = 3
    hint_after_misses: int = 2
    reveal_after_misses: int = 3
    max_learning_streak: int = 3
    checkin_every_n_turns: int = 8
    context_turns: int = 6
    max_input_chars: int = 200
    max_reply_chars: int = 240
    session_ttl_days: int = 30


def load_settings(_env_file: str | None = ".env") -> Settings:
    """Build Settings, turning missing required variables into a clear startup exit."""

    try:
        return Settings(_env_file=_env_file)
    except ValidationError as exc:
        missing = sorted(
            {
                str(error["loc"][0]).upper()
                for error in exc.errors()
                if error["type"] == "missing"
            }
        )
        if missing:
            names = ", ".join(missing)
            raise SystemExit(
                f"Missing required environment variable(s): {names}"
            ) from exc
        raise


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings."""

    return load_settings()
