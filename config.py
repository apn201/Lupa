"""Environment, markers and thresholds. Read once; everything else imports from here."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The four markers (build spec 0.4). Every API response and every screen row
# carries one, so nothing proposed is ever mistaken for a PayPal endpoint.
PAYPAL = "●"    # live sandbox call
PROPOSED = "◇"  # the API this project proposes
AI = "◆"        # interpretation by a model
POLICY = "■"    # deterministic enforcement

MARKERS = {PAYPAL: "PAYPAL", PROPOSED: "PROPOSED", AI: "AI", POLICY: "POLICY"}


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader. Real environment variables win over the file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    db_path: str = "var/lupa.db"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_webhook_id: str = ""
    card_number: str = ""
    card_expiry: str = "2030-12"
    card_name: str = "Test Buyer"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_max_calls_per_hour: int = 60
    llm_max_calls_per_day: int = 500
    llm_daily_spend_ceiling: float = 0.0
    llm_cost_per_1m_input: float = 0.0
    llm_cost_per_1m_output: float = 0.0
    llm_usage_path: str = "var/llm_usage.json"
    llm_kill_switch_path: str = "var/LLM_OFF"
    hold_hours: int = 72
    currency: str = "EUR"
    extra: dict = field(default_factory=dict)

    @property
    def paypal_enabled(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_model)

    def __post_init__(self) -> None:
        # Sandbox only (build spec 0.5). A live base URL is refused outright.
        if self.paypal_base_url and "sandbox" not in self.paypal_base_url:
            raise SystemExit("Lupa runs against the PayPal sandbox only. PAYPAL_BASE_URL must be a sandbox URL.")


def settings_from_env() -> Settings:
    load_dotenv()
    return Settings(
        db_path=_env("LUPA_DB", "var/lupa.db"),
        paypal_client_id=_env("PAYPAL_CLIENT_ID"),
        paypal_client_secret=_env("PAYPAL_CLIENT_SECRET"),
        paypal_base_url=_env("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com"),
        paypal_webhook_id=_env("PAYPAL_WEBHOOK_ID"),
        card_number=_env("LUPA_TEST_CARD_NUMBER"),
        card_expiry=_env("LUPA_TEST_CARD_EXPIRY", "2030-12"),
        card_name=_env("LUPA_TEST_CARD_NAME", "Test Buyer"),
        llm_base_url=_env("LLM_BASE_URL"),
        llm_api_key=_env("LLM_API_KEY"),
        llm_model=_env("LLM_MODEL"),
        llm_max_calls_per_hour=int(_float("LLM_MAX_CALLS_PER_HOUR", 60)),
        llm_max_calls_per_day=int(_float("LLM_MAX_CALLS_PER_DAY", 500)),
        llm_daily_spend_ceiling=_float("LLM_DAILY_SPEND_CEILING", 0),
        llm_cost_per_1m_input=_float("LLM_COST_PER_1M_INPUT", 0),
        llm_cost_per_1m_output=_float("LLM_COST_PER_1M_OUTPUT", 0),
        hold_hours=int(_float("LUPA_HOLD_HOURS", 72)),
    )


# Reconstruction thresholds (build spec 4).
FIXED_SPREAD_MAX = 0.05
MONTHLY_DAYS = range(28, 32)
WEEKLY_DAYS = range(7, 8)
YEARLY_DAYS = range(360, 371)
AMOUNT_JUMP_RATIO = 1.5
DEFAULT_MIN_CONFIDENCE = 0.95
DEFAULT_INCREASE_TOLERANCE_PCT = 20
