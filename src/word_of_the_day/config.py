# src/word_of_the_day/config.py
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API Credentials
    nyt_api_key: str = Field(default="", validation_alias="NYT_API_KEY")
    merriam_webster_api_key: str = Field(
        default="", validation_alias="MERRIAM_WEBSTER_API_KEY"
    )

    # Connector URLs & User Agents
    nyt_base_url: str = Field(
        default="https://api.nytimes.com", validation_alias="NYT_BASE_URL"
    )
    poetry_db_base_url: str = Field(
        default="https://poetrydb.org", validation_alias="POETRY_DB_BASE_URL"
    )
    quotable_base_url: str = Field(
        default="https://api.quotable.io", validation_alias="QUOTABLE_BASE_URL"
    )
    substack_base_url: str = Field(
        default="https://substack.com", validation_alias="SUBSTACK_BASE_URL"
    )
    wikipedia_base_url: str = Field(
        default="https://en.wikipedia.org", validation_alias="WIKIPEDIA_BASE_URL"
    )
    dictionary_base_url: str = Field(
        default="https://www.dictionaryapi.com/api/v3/references/collegiate/json/",
        validation_alias="DICTIONARY_BASE_URL",
    )
    podcast_feed_url: str = Field(
        default="https://rss.art19.com/merriam-websters-word-of-the-day",
        validation_alias="PODCAST_FEED_URL",
    )

    # User Agent details
    app_name: str = Field(default="WordOfTheDayApp", validation_alias="APP_NAME")
    app_version: str = Field(default="1.0.0", validation_alias="APP_VERSION")
    contact_email: str = Field(default="", validation_alias="CONTACT_EMAIL")

    wikipedia_app_name: str | None = Field(
        default=None, validation_alias="WIKIPEDIA_APP_NAME"
    )
    wikipedia_contact_email: str | None = Field(
        default=None, validation_alias="WIKIPEDIA_CONTACT_EMAIL"
    )
    wikipedia_version: str | None = Field(
        default=None, validation_alias="WIKIPEDIA_VERSION"
    )

    poetry_db_app_name: str | None = Field(
        default=None, validation_alias="POETRY_DB_APP_NAME"
    )
    poetry_db_contact_email: str | None = Field(
        default=None, validation_alias="POETRY_DB_CONTACT_EMAIL"
    )
    poetry_db_version: str | None = Field(
        default=None, validation_alias="POETRY_DB_VERSION"
    )

    # Pipeline configurations
    min_score: float = Field(default=2.3, validation_alias="MIN_SCORE")
    max_score: float = Field(default=4.0, validation_alias="MAX_SCORE")
    limit: int = Field(default=3, validation_alias="LIMIT")
    use_embeddings: bool = Field(default=True, validation_alias="USE_EMBEDDINGS")
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2", validation_alias="EMBEDDING_MODEL"
    )
    embedding_k: int = Field(default=5, validation_alias="EMBEDDING_K")
    seed_csv_path: str = Field(
        default="word_of_the_day_embeddings.csv", validation_alias="SEED_CSV_PATH"
    )
    cache_npz_path: str = Field(
        default="word_of_the_day_embeddings.npz", validation_alias="CACHE_NPZ_PATH"
    )

    # Substack configuration
    substack_category: str = Field(
        default="philosophy", validation_alias="SUBSTACK_CATEGORY"
    )
    substack_limit_pubs: int = Field(default=3, validation_alias="SUBSTACK_LIMIT_PUBS")
    substack_limit_posts: int = Field(
        default=3, validation_alias="SUBSTACK_LIMIT_POSTS"
    )
    substack_shuffle_pubs: bool = Field(
        default=True, validation_alias="SUBSTACK_SHUFFLE_PUBS"
    )

    # Web/API Configurations
    api_host: str = Field(default="127.0.0.1", validation_alias="API_HOST")
    api_port: int = Field(default=8000, validation_alias="API_PORT")
    cors_origins: list[str] = Field(default=["*"], validation_alias="CORS_ORIGINS")
    disable_api_docs: bool = Field(default=False, validation_alias="DISABLE_API_DOCS")

    # Logging configurations
    log_file: str = Field(default="logs/app.log", validation_alias="LOG_FILE")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_level_console: str = Field(default="INFO", validation_alias="LOG_LEVEL_CONSOLE")
    log_level_file: str = Field(default="DEBUG", validation_alias="LOG_LEVEL_FILE")
    log_max_bytes: int = Field(default=10485760, validation_alias="LOG_MAX_BYTES")
    log_backup_count: int = Field(default=5, validation_alias="LOG_BACKUP_COUNT")

    # Database
    db_path: str | None = Field(default=None, validation_alias="DB_PATH")

    # Scheduler configuration
    scheduler_enabled: bool = Field(default=True, validation_alias="SCHEDULER_ENABLED")

    # Admin configuration
    admin_password: str = Field(default="admin123", validation_alias="ADMIN_PASSWORD")


class SettingsProxy:
    def __getattr__(self, name: str) -> Any:
        return getattr(Settings(), name)


settings = SettingsProxy()
