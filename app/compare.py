"""Small, repeatable comparison runner; formal scoring belongs to v0.3."""

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from app.config import ROOT
from app.context import build_context
from app.errors import ResolutionError
from app.reasoner import Reasoner
from app.execution import configured_reasoners, close_reasoners, execute_context

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


def run_comparison(cases: list[dict], reasoners: dict[str, Reasoner]) -> dict:
    report = {"version": "0.2.0", "created_at": datetime.now(timezone.utc).isoformat(), "cases": []}
    for case in cases:
        row = {key: case[key] for key in ("case_id", "description", "expected")}
        row["results"] = {}
        # One context snapshot is supplied to every provider for this case.
        for name, reasoner in reasoners.items():
            row["results"][name] = execute_context(case["context"], reasoner)
        report["cases"].append(row)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("rule_based", "azure_openai", "both"), default="rule_based")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    reasoners = {}
    try:
        reasoners = configured_reasoners(args.provider)
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
        close_reasoners(reasoners)


if __name__ == "__main__":
    raise SystemExit(main())
