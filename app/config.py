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
