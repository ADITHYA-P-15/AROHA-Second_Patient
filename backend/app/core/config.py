from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "dev"
    secret_key: str = "change-me-before-production"
    database_url: str = "sqlite:///./second_patient.db"
    app_timezone: str = "Asia/Kolkata"
    demo_mode: bool = True
    seed_demo: bool = True
    demo_password: str = "Demo@1234"
    escalation_time_scale: float = 1.0
    cookie_secure: bool = False
    session_hours: int = 12
    log_level: str = "INFO"
    ai_provider: str = "none"
    ai_api_key: str = ""
    ai_model: str = ""
    git_sha: str = "dev"


settings = Settings()
