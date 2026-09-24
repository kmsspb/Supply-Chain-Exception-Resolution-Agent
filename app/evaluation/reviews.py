from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.evaluation.dataset import StrictModel, Text, canonical_hash


class ClaimReview(StrictModel):
    field: Literal["category", "summary", "recommended_action"]
    assertion: str = Field(min_length=1)
    verdict: Literal["supported", "unsupported", "uncertain"]
    explanation: Text
    evidence_ids: list[Text]


class ReviewEntry(StrictModel):
    case_id: Text
    provider: Literal["rule_based", "azure_openai"]
    run_id: Text
    output_hash: Text
    reviewer: Text | None = None
    reviewed_at: datetime | None = None
    rationale: Text | None = None
    action_correct: bool | None = Field(default=None, strict=True)
    escalation_recommended: bool | None = Field(default=None, strict=True)
    claims_complete: bool = Field(default=False, strict=True)
    claims: list[ClaimReview] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_review_provenance(self):
        submitted = self.action_correct is not None or self.escalation_recommended is not None or self.claims_complete or bool(self.claims)
        if submitted and (not self.reviewer or self.reviewed_at is None or not self.rationale):
            raise ValueError("Submitted judgements need reviewer, timestamp, and rationale")
        if self.reviewed_at is not None and self.reviewed_at.utcoffset() is None:
            raise ValueError("Review timestamp must include a timezone")
        return self


class ReviewFile(StrictModel):
    schema_version: Literal["0.3.0"] = "0.3.0"
    results_hash: Text
    instructions: str = "Only enter judgements actually made by the named human reviewer. Leave unreviewed fields null."
    entries: list[ReviewEntry]


def review_template(results: dict) -> ReviewFile:
    entries = [
        ReviewEntry(case_id=case["case_id"], provider=provider, run_id=result["run_id"], output_hash=result["output_hash"])
        for case in results["cases"] for provider, result in case["results"].items()
        if result["status"] == "success"
    ]
    return ReviewFile(results_hash=results["results_hash"], entries=entries)


def validate_reviews(results: dict, reviews: ReviewFile) -> dict[tuple[str, str], ReviewEntry]:
    if reviews.results_hash != results["results_hash"]:
        raise ValueError("Reviews refer to a different evaluation result")
    outcomes = {
        (case["case_id"], provider): (case, result)
        for case in results["cases"] for provider, result in case["results"].items()
    }
    validated = {}
    for entry in reviews.entries:
        key = (entry.case_id, entry.provider)
        if key in validated:
            raise ValueError("Duplicate review entry")
        if key not in outcomes:
            raise ValueError("Review case/provider does not exist")
        case, result = outcomes[key]
        if result["status"] != "success":
            raise ValueError("Failed runs cannot receive recommendation reviews")
        if entry.run_id != result["run_id"] or entry.output_hash != result["output_hash"]:
            raise ValueError("Stale or mismatched review")
        recommendation = result["recommendation"]
        if canonical_hash(recommendation) != entry.output_hash:
            raise ValueError("Reviewed output has changed")
        evidence_ids = {item["evidence_id"] for item in case["context"]["evidence"]}
        seen_claims = set()
        for claim in entry.claims:
            identity = (claim.field, claim.assertion)
            if identity in seen_claims:
                raise ValueError("Duplicate assertion review")
            seen_claims.add(identity)
            if not claim.assertion.strip() or claim.assertion not in recommendation[claim.field]:
                raise ValueError("Assertion must quote its output field exactly")
            if not set(claim.evidence_ids) <= evidence_ids:
                raise ValueError("Review references unknown evidence")
            if claim.verdict == "supported" and not claim.evidence_ids:
                raise ValueError("Supported claims require source evidence references")
        # A nonempty category always makes a factual classification assertion.
        if entry.claims_complete and not any(claim.field == "category" for claim in entry.claims):
            raise ValueError("Complete claim review must cover the category assertion")
        validated[key] = entry
    return validated
