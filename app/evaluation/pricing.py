from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.evaluation.dataset import StrictModel, Text, read_json


class PricingProfile(StrictModel):
    provider: Literal["azure_openai"]
    deployment: Text
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    effective_date: date
    source: Text
    input_per_million: Decimal | None = None
    cached_input_per_million: Decimal | None = None
    output_per_million: Decimal | None = None

    @field_validator("input_per_million", "cached_input_per_million", "output_per_million")
    @classmethod
    def nonnegative_rate(cls, value):
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("Rates must be finite and nonnegative")
        return value


class PricingFile(StrictModel):
    profiles: list[PricingProfile] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_deployments(self):
        keys = [(p.provider, p.deployment) for p in self.profiles]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate provider/deployment pricing profile")
        return self


def load_pricing(path: Path | None) -> PricingFile:
    return PricingFile.model_validate(read_json(path)) if path else PricingFile()


def _count(value):
    return value if type(value) is int and value >= 0 else None


def token_usage(provider: str, result: dict) -> dict:
    fields = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
    if provider == "rule_based":
        return {**dict.fromkeys(fields, 0), "valid_totals": True, "pricing_issue": None}
    usage = result.get("metadata", {}).get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    inputs = usage.get("input_tokens_details") or {}
    outputs = usage.get("output_tokens_details") or {}
    inputs = inputs if isinstance(inputs, dict) else {}
    outputs = outputs if isinstance(outputs, dict) else {}
    tokens = {
        "input_tokens": _count(usage.get("input_tokens")),
        "cached_input_tokens": _count(inputs.get("cached_tokens")),
        "output_tokens": _count(usage.get("output_tokens")),
        "reasoning_tokens": _count(outputs.get("reasoning_tokens")),
        "total_tokens": _count(usage.get("total_tokens")),
    }
    i, o, total = (tokens[key] for key in ("input_tokens", "output_tokens", "total_tokens"))
    present = i is not None and o is not None and total is not None
    inconsistent = present and i + o != total
    valid = present and not inconsistent
    cached, reasoning = tokens["cached_input_tokens"], tokens["reasoning_tokens"]
    if cached is not None and i is not None and cached > i:
        valid = False
        inconsistent = True
    if reasoning is not None and o is not None and reasoning > o:
        valid = False
        inconsistent = True
    issue = None
    if not valid:
        issue = "missing_or_inconsistent_usage"
    elif cached is None and i:
        issue = "missing_cached_input_breakdown"
    elif inputs.get("cache_write_tokens", 0) not in (0, None):
        issue = "unsupported_cache_write_pricing"
    elif any(value not in (0, None) for key, value in inputs.items() if key not in {"cached_tokens", "cache_write_tokens"}):
        issue = "unsupported_input_breakdown"
    elif any(value not in (0, None) for key, value in outputs.items() if key != "reasoning_tokens"):
        issue = "unsupported_output_breakdown"
    if inconsistent:
        # Inconsistent counts must not enter reported known subtotals.
        tokens = dict.fromkeys(fields)
    return {**tokens, "valid_totals": valid, "pricing_issue": issue}


def estimate_cost(provider: str, result: dict, pricing: PricingFile) -> dict:
    if provider == "rule_based":
        return {"status": "zero_model_cost", "amount": "0", "currency": None, "reason": None, "profile": None}
    profile = next((p for p in pricing.profiles if p.provider == provider and p.deployment == result.get("metadata", {}).get("deployment")), None)
    unavailable = {
        "status": "unavailable", "amount": None, "currency": profile.currency if profile else None,
        "reason": None, "profile": profile.model_dump(mode="json") if profile else None,
    }
    usage = token_usage(provider, result)
    reason = usage["pricing_issue"]
    if reason is None and profile is None:
        reason = "missing_pricing_profile"
    if reason is not None:
        return {**unavailable, "reason": reason}
    cached = usage["cached_input_tokens"] or 0
    uncached = usage["input_tokens"] - cached
    pairs = (
        (uncached, profile.input_per_million),
        (cached, profile.cached_input_per_million),
        (usage["output_tokens"], profile.output_per_million),
    )
    if any(count > 0 and rate is None for count, rate in pairs):
        return {**unavailable, "reason": "missing_required_rate"}
    amount = sum((Decimal(count) * rate for count, rate in pairs if rate is not None), Decimal(0)) / Decimal(1_000_000)
    return {**unavailable, "status": "estimated", "amount": format(amount, "f"), "reason": None}
