from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    storage_dir: str = "storage"
    max_recipients_per_job: int = 1000
    worker_batch_size: int = 10
    worker_poll_interval_seconds: float = 1.0
    worker_sweep_interval_seconds: float = 30.0
    max_attempts: int = 3
    lease_timeout_seconds: int = 300

settings = Settings()
