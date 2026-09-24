from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.evaluation.dataset import canonical_hash, load_dataset
from app.evaluation.pricing import PricingFile
from app.evaluation.reviews import ReviewFile, review_template, validate_reviews
from app.evaluation.runner import results_hash, run_evaluation, score_report
from app.reasoner import RuleBasedReasoner


@pytest.fixture
def evaluation_result():
    return run_evaluation(load_dataset(), {"rule_based": RuleBasedReasoner()})


@pytest.fixture
def submitted_review(evaluation_result):
    template = review_template(evaluation_result).model_dump(mode="json")
    entry = template["entries"][0]
    entry.update({
        "reviewer": "synthetic-test-reviewer", "reviewed_at": "2026-09-24T13:00:00Z",
        "rationale": "Synthetic unit-test judgement, not a real human review.",
        "action_correct": True, "escalation_recommended": False, "claims_complete": True,
        "claims": [{
            "field": "category", "assertion": "customs_documentation", "verdict": "supported",
            "explanation": "Test fixture refers to the paperwork note.", "evidence_ids": ["note:NOTE-7001"],
        }],
    })
    template["entries"] = [entry]
    return template


def test_template_has_no_invented_reviews(evaluation_result):
    template = review_template(evaluation_result)
    assert len(template.entries) == 30
    assert all(entry.reviewer is None and entry.action_correct is None and not entry.claims_complete for entry in template.entries)
    report = score_report(evaluation_result, template)
    assert report["scoring"]["review_status"] == "pending"
    assert report["scoring"]["metrics"]["overall"]["actions"]["accuracy"] is None


def test_partial_review_import_and_metric_coverage(evaluation_result, submitted_review):
    reviews = ReviewFile.model_validate(submitted_review)
    report = score_report(evaluation_result, reviews)
    assert report["scoring"]["review_status"] == "pending"
    metrics = report["scoring"]["metrics"]["providers"]["rule_based"]
    assert metrics["overall"]["actions"]["accuracy"] == 1
    assert metrics["overall"]["actions"]["coverage"] == pytest.approx(1 / 30)
    assert metrics["new_cases"]["actions"]["reviewed"] == 0
    assert metrics["families"]["missing_customs_documents"]["actions"]["coverage"] == 0.2
    assert report["scoring"]["reviews_hash"] == canonical_hash(reviews.model_dump(mode="json"))


@pytest.mark.parametrize("mutation", [
    lambda data: data["entries"].append(deepcopy(data["entries"][0])),
    lambda data: data.__setitem__("results_hash", "stale"),
    lambda data: data["entries"][0].__setitem__("output_hash", "stale"),
    lambda data: data["entries"][0].__setitem__("run_id", "other-run"),
    lambda data: data["entries"][0].__setitem__("provider", "azure_openai"),
    lambda data: data["entries"][0].__setitem__("case_id", "missing-case"),
    lambda data: data["entries"][0]["claims"][0].__setitem__("assertion", "not in the actual output"),
    lambda data: data["entries"][0]["claims"][0].__setitem__("evidence_ids", ["note:invented"]),
    lambda data: data["entries"][0]["claims"][0].__setitem__("evidence_ids", []),
    lambda data: data["entries"][0]["claims"].append(deepcopy(data["entries"][0]["claims"][0])),
    lambda data: data["entries"][0].__setitem__("claims", []),
])
def test_invalid_or_stale_reviews_rejected(evaluation_result, submitted_review, mutation):
    mutation(submitted_review)
    with pytest.raises(ValueError):
        validate_reviews(evaluation_result, ReviewFile.model_validate(submitted_review))


@pytest.mark.parametrize("field,value", [
    ("reviewer", None), ("reviewed_at", None), ("rationale", None),
    ("reviewed_at", "2026-09-24T13:00:00"), ("action_correct", "true"),
])
def test_review_provenance_and_strict_booleans(submitted_review, field, value):
    submitted_review["entries"][0][field] = value
    with pytest.raises(ValidationError):
        ReviewFile.model_validate(submitted_review)


def test_incomplete_claim_review_is_excluded(evaluation_result, submitted_review):
    submitted_review["entries"][0]["claims_complete"] = False
    report = score_report(evaluation_result, ReviewFile.model_validate(submitted_review))
    assert report["scoring"]["metrics"]["overall"]["claims"]["reviewed_outputs"] == 0
    assert report["scoring"]["metrics"]["overall"]["claims"]["unsupported_claim_rate"] is None


@pytest.mark.parametrize("change", [
    lambda result: result["cases"][0]["results"]["rule_based"]["recommendation"].__setitem__("summary", "changed"),
    lambda result: result["cases"][0]["expected"].__setitem__("category", "weather_delay"),
    lambda result: result["cases"][0]["context"]["note"].__setitem__("text", "changed"),
])
def test_changed_result_content_rejected(evaluation_result, change):
    change(evaluation_result)
    with pytest.raises(ValueError):
        score_report(evaluation_result)


def test_review_cannot_be_reused_after_output_rehash(evaluation_result, submitted_review):
    outcome = evaluation_result["cases"][0]["results"]["rule_based"]
    outcome["recommendation"]["summary"] = "New output"
    outcome["output_hash"] = canonical_hash(outcome["recommendation"])
    evaluation_result["results_hash"] = results_hash(evaluation_result)
    with pytest.raises(ValueError):
        score_report(evaluation_result, ReviewFile.model_validate(submitted_review))


def test_rescoring_reuses_pricing_snapshot_and_is_reproducible(evaluation_result):
    pricing = PricingFile.model_validate({"profiles": [{
        "provider": "azure_openai", "deployment": "test", "currency": "EUR",
        "effective_date": "2026-09-24", "source": "synthetic", "input_per_million": "1.23",
    }]})
    first = score_report(evaluation_result, pricing=pricing)
    second = score_report(first, review_template(first))
    assert first["results_hash"] == second["results_hash"]
    assert first["scoring"]["metrics"] == second["scoring"]["metrics"]
    assert first["scoring"]["pricing"] == second["scoring"]["pricing"]
