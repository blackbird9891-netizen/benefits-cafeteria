from pydantic_settings import BaseSettings

DEFAULT_SECRET = "dev-secret-change-in-production"


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения, значения по умолчанию — для локального запуска."""

    environment: str = "development"
    demo_mode: bool = True

    database_url: str = "sqlite:///./cafeteria.db"
    jwt_secret: str = DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 12 * 60

    cors_origins: str = "*"

    class Config:
        env_file = ".env"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("production", "prod")


settings = Settings()

# Умолчание, которое молча работает в продуктиве, опаснее отсутствующего:
# с известным секретом любой выпишет себе токен администратора.
if settings.is_production and settings.jwt_secret == DEFAULT_SECRET:
    raise RuntimeError(
        "JWT_SECRET не задан. В продуктивном окружении секрет по умолчанию запрещён."
    )
