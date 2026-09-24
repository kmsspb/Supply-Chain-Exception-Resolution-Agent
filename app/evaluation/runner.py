from datetime import datetime, timezone

from app.evaluation.dataset import EvaluationDataset, canonical_hash
from app.evaluation.metrics import score_groups
from app.evaluation.pricing import PricingFile, estimate_cost, token_usage
from app.evaluation.reviews import ReviewFile, review_template, validate_reviews
from app.execution import execute_context
from app.models import ResolutionRecommendation


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def results_hash(results: dict) -> str:
    return canonical_hash({key: value for key, value in results.items() if key not in {"results_hash", "scoring"}})


def run_evaluation(dataset: EvaluationDataset, reasoners: dict) -> dict:
    # All cases are validated before this function is called or any context is run.
    snapshot = dataset.model_dump(mode="json")
    report = {
        "schema_version": "0.3.0", "created_at": utc_now(),
        "dataset": snapshot, "dataset_hash": canonical_hash(snapshot), "cases": [],
    }
    contexts = [(case, case.context()) for case in dataset.cases]
    for case, context in contexts:
        context_data = context.model_dump(mode="json")
        row = {
            "case_id": case.case_id, "family": case.family, "origin": case.origin,
            "expected": case.expected.model_dump(mode="json"),
            "context": context_data, "context_hash": canonical_hash(context_data), "results": {},
        }
        for provider, reasoner in reasoners.items():
            result = execute_context(context, reasoner)
            result["output_hash"] = canonical_hash(result["recommendation"]) if result["status"] == "success" else None
            row["results"][provider] = result
        report["cases"].append(row)
    report["results_hash"] = results_hash(report)
    return report


def validate_results(report: dict) -> None:
    if report["schema_version"] != "0.3.0" or report["results_hash"] != results_hash(report):
        raise ValueError("Invalid or changed evaluation results")
    dataset = EvaluationDataset.model_validate(report["dataset"])
    if canonical_hash(dataset.model_dump(mode="json")) != report["dataset_hash"]:
        raise ValueError("Dataset snapshot hash mismatch")
    cases = {case.case_id: case for case in dataset.cases}
    if len(report["cases"]) != len(cases) or {row["case_id"] for row in report["cases"]} != set(cases):
        raise ValueError("Result case IDs do not match the dataset")
    run_ids = set()
    provider_set = None
    for row in report["cases"]:
        case = cases[row["case_id"]]
        if row["context_hash"] != canonical_hash(row["context"]) or row["context"] != case.context().model_dump(mode="json"):
            raise ValueError("Context has changed")
        if row["expected"] != case.expected.model_dump(mode="json") or row["family"] != case.family or row["origin"] != case.origin:
            raise ValueError("Case annotations have changed")
        names = set(row["results"])
        if not names or not names <= {"rule_based", "azure_openai"} or (provider_set is not None and names != provider_set):
            raise ValueError("Invalid or inconsistent provider set")
        provider_set = names
        for provider, result in row["results"].items():
            if not result["run_id"] or result["run_id"] in run_ids:
                raise ValueError("Missing or duplicated run ID")
            run_ids.add(result["run_id"])
            if result["status"] == "success":
                recommendation = ResolutionRecommendation.model_validate(result["recommendation"])
                if recommendation.run_id != result["run_id"] or recommendation.provider != provider or recommendation.exception_id != case.case_id:
                    raise ValueError("Recommendation identity mismatch")
                if result["output_hash"] != canonical_hash(result["recommendation"]):
                    raise ValueError("Recommendation output hash mismatch")
            elif result["status"] != "error" or result.get("output_hash") is not None or not result.get("error", {}).get("code"):
                raise ValueError("Invalid error outcome")


def score_report(results: dict, reviews: ReviewFile | None = None, pricing: PricingFile | None = None) -> dict:
    validate_results(results)
    pricing = pricing if pricing is not None else PricingFile.model_validate(results.get("scoring", {}).get("pricing", {"profiles": []}))
    reviews = reviews if reviews is not None else review_template(results)
    entries = validate_reviews(results, reviews)
    metrics = score_groups(results, entries, pricing)
    return {
        **results,
        "scoring": {
            "scored_at": utc_now(), "reviews_hash": canonical_hash(reviews.model_dump(mode="json")),
            "reviews": reviews.model_dump(mode="json"), "pricing": pricing.model_dump(mode="json"),
            "review_status": (
                "no_successful_outputs" if not metrics["overall"]["successful_outputs"] else
                "pending" if any(metrics["overall"][key]["pending"] for key in ("actions", "claims", "escalation")) else "complete"
            ),
            "metrics": metrics,
            "per_run": {
                result["run_id"]: {"usage": token_usage(provider, result), "cost": estimate_cost(provider, result, pricing)}
                for case in results["cases"] for provider, result in case["results"].items()
            },
        },
    }
