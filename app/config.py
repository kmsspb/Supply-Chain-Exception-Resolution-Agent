import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from app.errors import ConfigurationError

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    provider: str = "rule_based"
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    deployment: str = ""
    timeout_seconds: float = 30.0
    max_output_tokens: int = 4096

    @classmethod
    def from_env(cls, provider: str | None = None) -> "Settings":
        load_dotenv(ROOT / ".env", override=False)
        selected = provider or os.getenv("REASONER_PROVIDER", "rule_based")
        if selected not in {"rule_based", "azure_openai"}:
            raise ConfigurationError()
        if selected == "rule_based":
            return cls()
        try:
            settings = cls(
                provider=selected,
                base_url=os.getenv("AZURE_OPENAI_BASE_URL", "").strip(),
                api_key=os.getenv("AZURE_OPENAI_API_KEY", "").strip(),
                deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip(),
                timeout_seconds=float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "30")),
                max_output_tokens=int(os.getenv("AZURE_OPENAI_MAX_OUTPUT_TOKENS", "4096")),
            )
            settings.validate()
            return settings
        except (ValueError, OverflowError):
            raise ConfigurationError() from None

    def validate(self) -> None:
        url = urlparse(self.base_url)
        if (
            self.provider != "azure_openai"
            or not self.api_key or not self.deployment
            or url.scheme != "https" or not url.hostname
            or url.username or url.password or url.query or url.fragment
            or url.path.rstrip("/") != "/openai/v1"
            or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0
            or self.max_output_tokens <= 0
        ):
            raise ConfigurationError()


def _positive_float(name: str, default: str) -> float:
    try:
        value = float(os.getenv(name, default))
    except (ValueError, OverflowError):
        raise ConfigurationError() from None
    if not math.isfinite(value) or value <= 0:
        raise ConfigurationError()
    return value


def _base_url(name: str) -> str:
    value = os.getenv(name, "").strip().rstrip("/")
    parsed = urlparse(value)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not value or parsed.scheme not in ({"http", "https"} if loopback else {"https"})
        or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise ConfigurationError()
    return value


@dataclass(frozen=True)
class ConnectorSettings:
    mode: str = "fixture"
    erp_base_url: str = ""
    logistics_base_url: str = ""
    connect_timeout: float = 2.0
    read_timeout: float = 5.0
    write_timeout: float = 5.0
    pool_timeout: float = 2.0
    attempts: int = 3
    breaker_threshold: int = 5
    breaker_open_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ConnectorSettings":
        load_dotenv(ROOT / ".env", override=False)
        mode = os.getenv("CONNECTOR_MODE", "fixture").strip()
        if mode == "fixture":
            return cls()
        if mode != "http":
            raise ConfigurationError()
        try:
            settings = cls(
                mode=mode,
                erp_base_url=_base_url("ERP_BASE_URL"),
                logistics_base_url=_base_url("LOGISTICS_BASE_URL"),
                connect_timeout=_positive_float("CONNECTOR_CONNECT_TIMEOUT_SECONDS", "2"),
                read_timeout=_positive_float("CONNECTOR_READ_TIMEOUT_SECONDS", "5"),
                write_timeout=_positive_float("CONNECTOR_WRITE_TIMEOUT_SECONDS", "5"),
                pool_timeout=_positive_float("CONNECTOR_POOL_TIMEOUT_SECONDS", "2"),
                attempts=int(os.getenv("CONNECTOR_ATTEMPTS", "3")),
                breaker_threshold=int(os.getenv("CONNECTOR_BREAKER_THRESHOLD", "5")),
                breaker_open_seconds=_positive_float("CONNECTOR_BREAKER_OPEN_SECONDS", "30"),
            )
        except (ValueError, OverflowError):
            raise ConfigurationError() from None
        if settings.attempts <= 0 or settings.breaker_threshold <= 0:
            raise ConfigurationError()
        return settings


@dataclass(frozen=True)
class ActionSettings:
    database_path: Path

    @classmethod
    def from_env(cls) -> "ActionSettings":
        load_dotenv(ROOT / ".env", override=False)
        raw = os.getenv("ACTION_DB_PATH", "").strip()
        return cls(Path(raw) if raw else ROOT / ".runtime" / "actions.sqlite3")
