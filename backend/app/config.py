"""Runtime settings, read from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # SEC requires a descriptive User-Agent with contact e-mail.
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "CallWatch KAIST-DFMBA research contact@example.com")
    data_dir: Path = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
    database_url: str = os.getenv("DATABASE_URL", "")  # empty -> SQLite in data_dir

    # LLM: gemini | groq | openai | none
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini").lower()
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    api_ninjas_key: str = os.getenv("API_NINJAS_KEY", "")  # optional transcript source

    # Toss Securities Open API (read-only use). Calls only work from allow-listed server IPs.
    toss_client_id: str = os.getenv("TOSS_CLIENT_ID", "")
    toss_client_secret: str = os.getenv("TOSS_CLIENT_SECRET", "")
    toss_account_seq: str = os.getenv("TOSS_ACCOUNT_SEQ", "")
    # Owner key: when set, broker sync and money amounts require header X-Owner-Key (single-user deployments)
    owner_key: str = os.getenv("OWNER_KEY", "")

    # Multi-user sign-in (Supabase Auth). Either the project URL (JWKS, asymmetric keys) or the legacy JWT secret.
    supabase_url: str = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    # Accounts allowed to use the server-side Toss connection (comma separated e-mails)
    owner_emails: list[str] = field(default_factory=lambda: [e.strip().lower() for e in os.getenv("OWNER_EMAILS", "").split(",") if e.strip()])
    daily_analysis_limit: int = int(os.getenv("DAILY_ANALYSIS_LIMIT", "30"))
    # open access: anyone can browse without signing up
    featured: list[str] = field(default_factory=lambda: [t.strip().upper() for t in os.getenv(
        "FEATURED_TICKERS", "AAPL,MSFT,NVDA,GOOGL,TSLA,SPCX,C,LLY").split(",") if t.strip()])
    warm_featured: bool = os.getenv("WARM_FEATURED", "1") == "1"
    featured_refresh_hours: float = float(os.getenv("FEATURED_REFRESH_HOURS", "20"))
    anon_daily_analysis_limit: int = int(os.getenv("ANON_DAILY_ANALYSIS_LIMIT", "3"))
    qa_daily_limit: int = int(os.getenv("QA_DAILY_LIMIT", "20"))

    demo_mode: bool = _bool("DEMO_MODE", False)
    cache_ttl_hours: int = int(os.getenv("CACHE_TTL_HOURS", "24"))
    benchmark: str = os.getenv("BENCHMARK_TICKER", "SPY")
    cors_origins: list[str] = field(
        default_factory=lambda: [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.supabase_url or self.supabase_jwt_secret)

    @property
    def llm_enabled(self) -> bool:
        return (
            (self.llm_provider == "gemini" and bool(self.gemini_api_key))
            or (self.llm_provider == "groq" and bool(self.groq_api_key))
            or (self.llm_provider == "openai" and bool(self.openai_api_key))
        )

    @property
    def llm_label(self) -> str:
        if not self.llm_enabled:
            return "rule-based (LLM key 없음)"
        return {
            "gemini": f"Gemini · {self.gemini_model}",
            "groq": f"Groq · {self.groq_model}",
            "openai": f"OpenAI-compatible · {self.openai_model}",
        }[self.llm_provider]


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
