from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "dev"
    secret_key: str = "change-me-before-production"
    database_url: str = "sqlite:///./second_patient.db"
    app_timezone: str = "Asia/Kolkata"
    demo_mode: bool = True
    seed_demo: bool = True
    # Build the larger fictional population (more families, caretakers, hospital staff, 30 days of history) with the demo.
    demo_population: bool = True
    demo_password: str = "Demo@1234"
    escalation_time_scale: float = 1.0
    # Offer cover and rebalance overload automatically; the replacement must still accept.
    auto_coordination: bool = True
    cookie_secure: bool = False
    session_hours: int = 12
    log_level: str = "INFO"
    ai_provider: str = "none"
    ai_api_key: str = ""
    ai_model: str = ""
    # AI is optional and advisory. Speech: Gemma first, Groq fallback. Text tasks: Groq first, Gemma fallback. Keys stay on the server.
    gemini_api_key: str = ""
    gemma_model: str = "gemma-3n-e4b-it"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_api_key: str = ""
    groq_stt_model: str = "whisper-large-v3-turbo"
    groq_text_model: str = "llama-3.3-70b-versatile"
    ai_speech_order: str = "gemma,groq"
    ai_text_order: str = "groq,gemma"
    ai_timeout_seconds: float = 20.0
    voice_max_bytes: int = 3_000_000
    git_sha: str = "dev"


settings = Settings()
