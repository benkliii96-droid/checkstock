from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://checkstock:checkstock@localhost:5432/checkstock"
    seed_on_start: bool = True


settings = Settings()
