from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    storage_dir: str = "storage"
    max_recipients_per_job: int = 1000

settings = Settings()
