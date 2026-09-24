"""Small, repeatable comparison runner; formal scoring belongs to v0.3."""

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.audit import get_events
from app.config import ROOT, Settings
from app.context import build_context
from app.errors import ResolutionError
from app.reasoner import Reasoner, create_reasoner
from app.service import analyse_context

CASES_PATH = ROOT / "data" / "comparison_cases.json"


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    source = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for case in source["cases"]:
        records = deepcopy(source["base"])
        records["exception"]["exception_id"] = case["case_id"]
        for record, fields in case.get("overrides", {}).items():
            records[record].update(fields)
        cases.append({
            "case_id": case["case_id"], "description": case["description"],
            "expected": case["expected"], "context": build_context(**records),
        })
    return cases


class _UnavailableReasoner:
    def __init__(self, provider: str, error: ResolutionError):
        self.provider = provider
        self.error_type = type(error)

    def describe(self):
        return {}

    def resolve(self, context):
        raise self.error_type()


def run_comparison(cases: list[dict], reasoners: dict[str, Reasoner]) -> dict:
    report = {"version": "0.2.0", "created_at": datetime.now(timezone.utc).isoformat(), "cases": []}
    for case in cases:
        row = {key: case[key] for key in ("case_id", "description", "expected")}
        row["results"] = {}
        # One context snapshot is supplied to every provider for this case.
        for name, reasoner in reasoners.items():
            try:
                recommendation = analyse_context(case["context"], reasoner)
                run_id = recommendation.run_id
                outcome = {"status": "success", "recommendation": recommendation.model_dump(mode="json")}
            except ResolutionError as exc:
                run_id = exc.run_id
                outcome = {"status": "error", "error": {"code": exc.code, "message": exc.message}}
            events = get_events(case["context"].exception["exception_id"], run_id)
            metadata = next((
                event["details"].get("metadata", {}) for event in reversed(events)
                if event["event_type"] in {"model_completed", "model_failed"}
            ), {})
            outcome.update({
                "run_id": run_id, "metadata": metadata,
                "elapsed_ms": events[-1]["details"].get("elapsed_ms") if events else None,
                "trace": events,
            })
            row["results"][name] = outcome
        report["cases"].append(row)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("rule_based", "azure_openai", "both"), default="rule_based")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    names = ("rule_based", "azure_openai") if args.provider == "both" else (args.provider,)
    reasoners = {}
    try:
        for name in names:
            try:
                reasoners[name] = create_reasoner(Settings.from_env(provider=name))
            except ResolutionError as exc:
                reasoners[name] = _UnavailableReasoner(name, exc)
        report = run_comparison(load_cases(), reasoners)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
        errors = sum(result["status"] == "error" for case in report["cases"] for result in case["results"].values())
        print(f"Wrote {len(report['cases'])} cases to {args.output}; {errors} provider errors.")
        return 1 if errors else 0
    except (ResolutionError, OSError, ValueError, KeyError, TypeError):
        print("Comparison could not read its fixtures or write its report.", file=sys.stderr)
        return 2
    finally:
        for reasoner in reasoners.values():
            client = getattr(reasoner, "client", None)
            if client is not None:
                client.close()


if __name__ == "__main__":
    raise SystemExit(main())
