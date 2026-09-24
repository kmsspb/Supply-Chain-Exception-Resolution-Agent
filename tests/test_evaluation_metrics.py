from copy import deepcopy

import pytest

from app.evaluation.metrics import aggregate, latency_stats
from app.evaluation.pricing import PricingFile
from app.evaluation.reviews import ReviewEntry


def row(case_id, actual="expected", expected="expected", escalation=False, elapsed=10, status="success"):
    evidence = {"evidence_id": "erp:1", "source": "ERP", "fact": "fact", "raw_reference": "1"}
    case = {
        "case_id": case_id, "context": {"evidence": [evidence]},
        "expected": {"category": expected, "manual_escalation": escalation},
    }
    result = {
        "status": status, "run_id": case_id, "elapsed_ms": elapsed, "provider_elapsed_ms": elapsed / 2,
        "metadata": {}, "error": {"code": "provider_timeout"},
        "recommendation": {"category": actual, "cause_evidence_ids": ["erp:1"], "action_evidence_ids": ["erp:1"], "evidence": [deepcopy(evidence)]},
    }
    return case, "rule_based", result


def review(case_id, action=None, escalation=None, claims=None, complete=False):
    return ReviewEntry(
        case_id=case_id, provider="rule_based", run_id=case_id, output_hash="test-hash",
        reviewer="synthetic-test-reviewer", reviewed_at="2026-09-24T12:00:00Z",
        rationale="Synthetic test judgement, not a production human review.",
        action_correct=action, escalation_recommended=escalation,
        claims=claims or [], claims_complete=complete,
    )


def claim(verdict):
    return {"field": "category", "assertion": "expected", "verdict": verdict,
            "explanation": "Synthetic test judgement.", "evidence_ids": ["erp:1"]}


def test_hand_calculated_metrics_with_partial_reviews_and_error():
    rows = [row("a", actual=" EXPECTED ", escalation=True), row("b", actual="wrong"), row("c", escalation=True), row("d", status="error")]
    reviews = {
        ("a", "rule_based"): review("a", action=True, escalation=True, claims=[claim("supported"), claim("unsupported"), claim("uncertain")], complete=True),
        ("b", "rule_based"): review("b", action=False, escalation=True),
        ("c", "rule_based"): review("c", escalation=False, claims=[claim("unsupported")], complete=False),
    }
    score = aggregate(rows, reviews, PricingFile())
    assert score["classification"]["attempt_accuracy"] == 0.5
    assert score["classification"]["successful_output_accuracy"] == pytest.approx(2 / 3)
    assert score["classification"]["confusion"]["expected"]["__provider_error__"] == 1
    assert score["actions"]["accuracy"] == 0.5
    assert score["actions"]["coverage"] == pytest.approx(2 / 3)
    assert score["actions"]["pending"] == 1
    assert score["claims"]["unsupported_claim_rate"] == 0.5
    assert score["claims"]["uncertainty_rate"] == pytest.approx(1 / 3)
    assert score["claims"]["unsupported"] == 1  # Partial claim review was excluded.
    assert score["claims"]["coverage"] == pytest.approx(1 / 3)
    assert score["escalation"]["true_positive"] == 1
    assert score["escalation"]["false_positive"] == 1
    assert score["escalation"]["false_negative"] == 1
    assert score["escalation"]["accuracy"] == pytest.approx(1 / 3)
    assert score["escalation"]["precision"] == score["escalation"]["recall"] == 0.5
    assert score["provider_errors"] == 1
    assert score["latency"]["success"]["analysis"]["count"] == 3
    assert score["latency"]["error"]["analysis"]["count"] == 1


def test_unknown_metrics_stay_null_and_claim_uncertainty_not_supported():
    score = aggregate([row("a")], {}, PricingFile())
    assert score["actions"]["accuracy"] is None
    assert score["claims"]["unsupported_claim_rate"] is None
    assert score["escalation"]["accuracy"] is None
    assert score["actions"]["coverage"] == 0
    entry = review("a", claims=[claim("uncertain")], complete=True)
    score = aggregate([row("a")], {("a", "rule_based"): entry}, PricingFile())
    assert score["claims"]["unsupported_claim_rate"] is None
    assert score["claims"]["uncertainty_rate"] == 1
    assert score["claims"]["verdict_coverage"] == 0


def test_escalation_does_not_use_approval_flag_and_handles_zero_denominators():
    item = row("a", escalation=False)
    item[2]["recommendation"]["human_approval_required"] = True
    score = aggregate([item], {("a", "rule_based"): review("a", escalation=False)}, PricingFile())
    assert score["escalation"]["accuracy"] == 1
    assert score["escalation"]["precision"] is None
    assert score["escalation"]["recall"] is None
    empty = aggregate([], {}, PricingFile())
    assert empty["classification"]["attempt_accuracy"] is None
    assert empty["cost"]["total"] is None


def test_nearest_rank_latency_and_missing_values():
    stats = latency_stats(list(range(1, 21)) + [None, float("nan"), -1])
    assert stats == {"count": 20, "mean_ms": 10.5, "median_ms": 10.5, "p95_ms": 19}
    assert latency_stats([5])["p95_ms"] == 5
    assert latency_stats([])["p95_ms"] is None


def test_citation_integrity_is_separate_from_semantic_support():
    first = row("a")
    second = deepcopy(row("b"))
    second[2]["recommendation"]["evidence"][0]["fact"] = "invented"
    score = aggregate([first, second], {}, PricingFile())
    assert score["citations"] == {"valid_outputs": 1, "checked_outputs": 2}
    assert score["claims"]["unsupported_claim_rate"] is None
