from dataclasses import dataclass
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
    match_algorithm_version: str = os.getenv("MATCH_ALGORITHM_VERSION", "match_v1")

    def __post_init__(self) -> None:
        if self.match_algorithm_version not in {"match_v1", "match_v2"}:
            raise ValueError("MATCH_ALGORITHM_VERSION must be match_v1 or match_v2")


settings = Settings()
