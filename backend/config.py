from dataclasses import dataclass, field
import os


@dataclass(frozen=True)
class Settings:
    app_mode: str = os.getenv("APP_MODE", "demo")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./fsp_signal.db")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8080")
    smtp_host: str = os.getenv("SMTP_HOST", "localhost")
    smtp_port: int = int(os.getenv("SMTP_PORT", "1025"))
    smtp_from: str = os.getenv("SMTP_FROM", "demo@example.test")
    session_secure: bool = os.getenv("SESSION_SECURE", "false").lower() == "true"
    fsp_provider: str = os.getenv("FSP_PROVIDER", "mock")
    match_algorithm_version: str = os.getenv("MATCH_ALGORITHM_VERSION", "match_v2")
    frontierai_base_url: str = field(default_factory=lambda: os.getenv(
        "FRONTIERAI_BASE_URL", "https://gateway.frontierai.ru/v1/chat/completions"))
    frontierai_model: str = field(default_factory=lambda: os.getenv(
        "FRONTIERAI_MODEL", "qwen3.8-27b-4a100"))
    frontierai_api_key: str | None = field(
        default_factory=lambda: os.getenv("FRONTIERAI_API_KEY") or None, repr=False)
    assistant_max_input_chars: int = field(default_factory=lambda: int(
        os.getenv("AI_ASSISTANT_MAX_INPUT_CHARS", "2000")))
    assistant_max_output_tokens: int = field(default_factory=lambda: int(
        os.getenv("AI_ASSISTANT_MAX_OUTPUT_TOKENS", "800")))
    assistant_timeout_seconds: float = field(default_factory=lambda: float(
        os.getenv("AI_ASSISTANT_TIMEOUT_SECONDS", "30")))

    def __post_init__(self) -> None:
        if self.match_algorithm_version not in {"match_v1", "match_v2"}:
            raise ValueError("MATCH_ALGORITHM_VERSION must be match_v1 or match_v2")
        if not 1 <= self.assistant_max_input_chars <= 2000:
            raise ValueError("AI_ASSISTANT_MAX_INPUT_CHARS must be between 1 and 2000")
        if not 1 <= self.assistant_max_output_tokens <= 800:
            raise ValueError("AI_ASSISTANT_MAX_OUTPUT_TOKENS must be between 1 and 800")
        if not 0 < self.assistant_timeout_seconds <= 30:
            raise ValueError("AI_ASSISTANT_TIMEOUT_SECONDS must be greater than 0 and at most 30")


settings = Settings()
