from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения, значения по умолчанию — для локального запуска."""

    database_url: str = "sqlite:///./cafeteria.db"
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 12 * 60

    cors_origins: str = "*"

    class Config:
        env_file = ".env"


settings = Settings()
