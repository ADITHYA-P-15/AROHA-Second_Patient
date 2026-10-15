from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "dev"
    secret_key: str = "change-me-before-production"
    database_url: str = "sqlite:///./second_patient.db"
    app_timezone: str = "Asia/Kolkata"
    demo_mode: bool = True
    seed_demo: bool = True
    # Staged rollout: a feature that is not listed here is off. New features ship dark and are switched on per environment ("*" = all).
    features: str = "voice_notes,insights,reminders,progress_report,checkins,directory,ratings,team_builder"
    # Set to false on web-only instances. The scheduler also takes a database lock, so a second instance never double-runs it.
    run_scheduler: bool = True
    # Background cadence. Small hosts (shared CPU, remote database) do better with longer gaps; reminders are minutes-grained anyway.
    scheduler_tick_seconds: int = 15
    scheduler_heavy_seconds: int = 60
    # How often open browsers refresh their notification bell (served to the UI in /api/v1/meta).
    client_poll_seconds: int = 5
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
    # AI is optional and advisory; keys stay on the server. Measured on real keys (see docs/AI.md):
    #   speech: Groq whisper-large-v3 first (best for Hindi/Kannada/Telugu), a Gemini model on the Google key as the fallback;
    #   text:   Groq gpt-oss first, Gemma 4 (Google key) as the fallback.
    # Gemma models on the Gemini API reject audio today; list "gemma" in AI_SPEECH_ORDER to try one when that changes.
    gemini_api_key: str = ""
    gemma_model: str = "gemma-4-31b-it"
    gemini_speech_model: str = "gemini-flash-lite-latest"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_stt_model: str = "whisper-large-v3"
    groq_text_model: str = "openai/gpt-oss-120b"
    ai_speech_order: str = "groq,gemini"
    ai_text_order: str = "groq,gemma"
    ai_timeout_seconds: float = 15.0       # speech: Groq answers in about a second
    ai_text_timeout_seconds: float = 8.0   # urgency suggestion: never hold up a patient's request for long
    voice_max_bytes: int = 3_000_000
    git_sha: str = "dev"
    # JSON merged over core/reputation_policy.DEFAULT_POLICY (weights, windows, limits); validated at start-up.
    reputation_policy: str = ""
    # JSON merged over core/checkin_policy.DEFAULT_POLICY (which tasks need a check-in, grace, missing point); validated at start-up.
    checkin_policy: str = ""
    # JSON merged over core/matcher_policy.DEFAULT_POLICY (reputation and preference points in the Backup Matcher); validated at start-up.
    matcher_policy: str = ""


    @field_validator("database_url")
    @classmethod
    def _driver(cls, value: str) -> str:
        """Hosting platforms hand out postgres:// or postgresql:// URLs; this app uses the psycopg 3 driver."""
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix): return "postgresql+psycopg://" + value[len(prefix):]
        return value

    def feature(self, name: str) -> bool:
        enabled = {f.strip().lower() for f in self.features.split(",") if f.strip()}
        return "*" in enabled or name.lower() in enabled

    @property
    def feature_list(self) -> list[str]:
        return sorted({f.strip().lower() for f in self.features.split(",") if f.strip()})


settings = Settings()
