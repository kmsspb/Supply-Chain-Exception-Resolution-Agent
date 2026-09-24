from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.evaluation.metrics import aggregate
from app.evaluation.pricing import PricingFile, estimate_cost, token_usage


@pytest.fixture
def pricing():
    return PricingFile.model_validate({"profiles": [{
        "provider": "azure_openai", "deployment": "test-deployment", "currency": "USD",
        "effective_date": "2026-09-24", "source": "Synthetic test rates, not actual Azure prices",
        "input_per_million": "2", "cached_input_per_million": "0.5", "output_per_million": "6",
    }]})


@pytest.fixture
def outcome():
    return {"status": "error", "error": {"code": "invalid_provider_output"}, "metadata": {
        "deployment": "test-deployment", "usage": {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100,
        "input_tokens_details": {"cached_tokens": 200}, "output_tokens_details": {"reasoning_tokens": 40}},
    }}


def test_decimal_cached_pricing_includes_failed_usage_without_double_reasoning(pricing, outcome):
    cost = estimate_cost("azure_openai", outcome, pricing)
    assert cost["amount"] == "0.0023"  # (800*2 + 200*0.5 + 100*6) / 1e6
    assert cost["currency"] == "USD"
    assert cost["profile"]["source"].startswith("Synthetic")
    usage = token_usage("azure_openai", outcome)
    assert usage["total_tokens"] == 1100
    assert usage["reasoning_tokens"] == 40


def test_missing_prices_usage_or_cached_breakdown_is_not_free(pricing, outcome):
    assert estimate_cost("azure_openai", outcome, PricingFile())["reason"] == "missing_pricing_profile"
    assert estimate_cost("azure_openai", {"metadata": {}}, pricing)["amount"] is None
    pricing.profiles[0].cached_input_per_million = None
    assert estimate_cost("azure_openai", outcome, pricing)["reason"] == "missing_required_rate"
    del outcome["metadata"]["usage"]["input_tokens_details"]
    assert estimate_cost("azure_openai", outcome, pricing)["reason"] == "missing_cached_input_breakdown"


@pytest.mark.parametrize("mutation,reason", [
    (lambda u: u.__setitem__("total_tokens", 1200), "missing_or_inconsistent_usage"),
    (lambda u: u["input_tokens_details"].__setitem__("cached_tokens", 1001), "missing_or_inconsistent_usage"),
    (lambda u: u["output_tokens_details"].__setitem__("reasoning_tokens", 101), "missing_or_inconsistent_usage"),
    (lambda u: u["input_tokens_details"].__setitem__("cache_write_tokens", 10), "unsupported_cache_write_pricing"),
    (lambda u: u["input_tokens_details"].__setitem__("audio_tokens", 5), "unsupported_input_breakdown"),
    (lambda u: u["output_tokens_details"].__setitem__("audio_tokens", 5), "unsupported_output_breakdown"),
])
def test_unsupported_or_inconsistent_usage(pricing, outcome, mutation, reason):
    mutation(outcome["metadata"]["usage"])
    assert estimate_cost("azure_openai", outcome, pricing)["reason"] == reason


def test_partial_usage_keeps_known_tokens(outcome):
    del outcome["metadata"]["usage"]["output_tokens"]
    usage = token_usage("azure_openai", outcome)
    assert usage["input_tokens"] == 1000
    assert usage["output_tokens"] is None
    assert not usage["valid_totals"]


def test_known_cost_subtotal_and_unknown_usage_coverage(pricing, outcome):
    case = {"case_id": "a", "expected": {"category": "unknown_logistics_exception"}}
    unknown = {"status": "error", "error": {"code": "provider_timeout"}, "metadata": {}}
    score = aggregate([(case, "azure_openai", outcome), (case, "azure_openai", unknown)], {}, pricing)
    assert score["cost"]["known_subtotals"] == {"USD": "0.0023"}
    assert score["cost"]["coverage"] == 0.5
    assert score["cost"]["total"] is None
    assert score["tokens"]["input_tokens"]["known_subtotal"] == 1000
    assert score["tokens"]["total_tokens"]["coverage"] == 0.5


def test_baseline_cost_and_tokens_are_zero():
    assert estimate_cost("rule_based", {}, PricingFile())["amount"] == "0"
    assert token_usage("rule_based", {})["total_tokens"] == 0


@pytest.mark.parametrize("rate", ["-1", "NaN", "Infinity"])
def test_invalid_rates_rejected(pricing, rate):
    data = pricing.model_dump(mode="json")
    data["profiles"][0]["input_per_million"] = rate
    with pytest.raises(ValidationError):
        PricingFile.model_validate(data)


def test_duplicate_profiles_rejected(pricing):
    data = pricing.model_dump(mode="json")
    data["profiles"].append(deepcopy(data["profiles"][0]))
    with pytest.raises(ValidationError):
        PricingFile.model_validate(data)
