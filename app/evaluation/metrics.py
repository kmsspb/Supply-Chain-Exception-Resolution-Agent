import math
from collections import Counter
from decimal import Decimal
from statistics import mean, median

from app.evaluation.pricing import PricingFile, estimate_cost, token_usage


def ratio(numerator: int, denominator: int):
    return numerator / denominator if denominator else None


def latency_stats(values) -> dict:
    known = sorted(value for value in values if type(value) in (int, float) and math.isfinite(value) and value >= 0)
    return {
        "count": len(known), "mean_ms": mean(known) if known else None,
        "median_ms": median(known) if known else None,
        "p95_ms": known[math.ceil(0.95 * len(known)) - 1] if known else None,
    }


def citations_valid(case: dict, result: dict) -> bool:
    recommendation = result["recommendation"]
    catalogue = {item["evidence_id"]: item for item in case["context"]["evidence"]}
    cause, action = recommendation["cause_evidence_ids"], recommendation["action_evidence_ids"]
    returned = {item["evidence_id"]: item for item in recommendation["evidence"]}
    return bool(cause and action) and set(cause + action) <= returned.keys() and all(
        item == catalogue.get(identifier) for identifier, item in returned.items()
    )


def aggregate(rows: list[tuple], reviews: dict, pricing: PricingFile) -> dict:
    """rows are (case, provider, result); unknowns never enter known denominators."""
    successful = [(case, provider, result) for case, provider, result in rows if result["status"] == "success"]
    correct = sum(result["recommendation"]["category"].strip().casefold() == case["expected"]["category"].strip().casefold() for case, _, result in successful)
    confusion = {}
    for case, _, result in rows:
        actual = result["recommendation"]["category"].strip().casefold() if result["status"] == "success" else "__provider_error__"
        expected = case["expected"]["category"]
        confusion.setdefault(expected, Counter())[actual] += 1

    action_reviews = []
    escalation = Counter({"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0})
    claim_verdicts = Counter({"supported": 0, "unsupported": 0, "uncertain": 0})
    claims_reviewed = outputs_with_unsupported = 0
    for case, provider, _ in successful:
        review = reviews.get((case["case_id"], provider))
        if review is None:
            continue
        if review.action_correct is not None:
            action_reviews.append(review.action_correct)
        if review.escalation_recommended is not None:
            predicted, expected = review.escalation_recommended, case["expected"]["manual_escalation"]
            key = ("true_" if predicted == expected else "false_") + ("positive" if predicted else "negative")
            escalation[key] += 1
        if review.claims_complete:
            claims_reviewed += 1
            claim_verdicts.update(claim.verdict for claim in review.claims)
            outputs_with_unsupported += any(claim.verdict == "unsupported" for claim in review.claims)

    usage = [token_usage(provider, result) for _, provider, result in rows]
    token_metrics = {}
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens", "total_tokens"):
        values = [item[key] for item in usage if item[key] is not None]
        token_metrics[key] = {
            "known_subtotal": sum(values) if values else None,
            "known_runs": len(values), "coverage": ratio(len(values), len(rows)),
        }
    costs = [estimate_cost(provider, result, pricing) for _, provider, result in rows]
    subtotals = {}
    for cost in costs:
        if cost["status"] == "estimated":
            currency = cost["currency"]
            subtotals[currency] = subtotals.get(currency, Decimal(0)) + Decimal(cost["amount"])
    unknown_costs = sum(cost["status"] == "unavailable" for cost in costs)
    known_zero = sum(cost["status"] == "zero_model_cost" for cost in costs)
    cost_total = None
    if rows and unknown_costs == 0 and len(subtotals) <= 1:
        cost_total = {"amount": format(sum(subtotals.values(), Decimal(0)), "f"), "currency": next(iter(subtotals), None)}
    completed_escalations = sum(escalation.values())
    claim_count = sum(claim_verdicts.values())
    supported_or_not = claim_verdicts["supported"] + claim_verdicts["unsupported"]
    eligible = len(successful)
    return {
        "attempts": len(rows), "successful_outputs": eligible,
        "provider_errors": len(rows) - eligible,
        "error_codes": dict(Counter(result["error"]["code"] for _, _, result in rows if result["status"] == "error")),
        "classification": {
            "correct": correct, "attempt_accuracy": ratio(correct, len(rows)),
            "successful_output_accuracy": ratio(correct, eligible), "confusion": confusion,
        },
        "actions": {"correct": sum(action_reviews), "reviewed": len(action_reviews),
                    "accuracy": ratio(sum(action_reviews), len(action_reviews)),
                    "coverage": ratio(len(action_reviews), eligible), "pending": eligible - len(action_reviews)},
        "claims": {
            **claim_verdicts, "reviewed_outputs": claims_reviewed,
            "coverage": ratio(claims_reviewed, eligible), "pending": eligible - claims_reviewed,
            "unsupported_claim_rate": ratio(claim_verdicts["unsupported"], supported_or_not),
            "uncertainty_rate": ratio(claim_verdicts["uncertain"], claim_count),
            "verdict_coverage": ratio(supported_or_not, claim_count),
            "outputs_with_unsupported_claims": outputs_with_unsupported,
        },
        "escalation": {
            **escalation, "reviewed": completed_escalations, "pending": eligible - completed_escalations,
            "coverage": ratio(completed_escalations, eligible),
            "accuracy": ratio(escalation["true_positive"] + escalation["true_negative"], completed_escalations),
            "precision": ratio(escalation["true_positive"], escalation["true_positive"] + escalation["false_positive"]),
            "recall": ratio(escalation["true_positive"], escalation["true_positive"] + escalation["false_negative"]),
        },
        "citations": {"valid_outputs": sum(citations_valid(case, result) for case, _, result in successful), "checked_outputs": eligible},
        "latency": {
            status: {
                "analysis": latency_stats(result.get("elapsed_ms") for _, _, result in rows if result["status"] == status),
                "provider": latency_stats(result.get("provider_elapsed_ms") for _, _, result in rows if result["status"] == status),
            } for status in ("success", "error")
        },
        "tokens": token_metrics,
        "cost": {
            "known_subtotals": {key: format(value, "f") for key, value in subtotals.items()},
            "zero_model_cost_runs": known_zero, "estimated_runs": len(rows) - unknown_costs - known_zero,
            "unavailable_runs": unknown_costs, "coverage": ratio(len(rows) - unknown_costs, len(rows)),
            "total": cost_total,
            "unavailable_reasons": dict(Counter(cost["reason"] for cost in costs if cost["status"] == "unavailable")),
        },
    }


def score_groups(results: dict, reviews: dict, pricing: PricingFile) -> dict:
    rows = [(case, provider, result) for case in results["cases"] for provider, result in case["results"].items()]
    providers = sorted({provider for _, provider, _ in rows})
    families = sorted({case["family"] for case, _, _ in rows})
    groups = {"overall": aggregate(rows, reviews, pricing), "providers": {}}
    for provider in providers:
        selected = [row for row in rows if row[1] == provider]
        groups["providers"][provider] = {
            "overall": aggregate(selected, reviews, pricing),
            "new_cases": aggregate([row for row in selected if row[0]["origin"] == "new"], reviews, pricing),
            "families": {family: aggregate([row for row in selected if row[0]["family"] == family], reviews, pricing) for family in families},
        }
    return groups
