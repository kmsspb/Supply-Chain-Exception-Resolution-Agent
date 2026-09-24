"""Run synthetic evaluations or import human reviews without additional model calls."""

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from app.errors import ResolutionError
from app.evaluation.dataset import DATASET_PATH, load_dataset, read_json
from app.evaluation.pricing import load_pricing
from app.evaluation.reporting import write_reports
from app.evaluation.reviews import ReviewFile
from app.evaluation.runner import run_evaluation, score_report
from app.execution import close_reasoners, configured_reasoners


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the fixed reasoners on a versioned dataset")
    run.add_argument("--provider", choices=("rule_based", "azure_openai", "both"), default="rule_based")
    run.add_argument("--dataset", type=Path, default=DATASET_PATH)
    score = commands.add_parser("score", help="Import structured human reviews; makes no provider calls")
    score.add_argument("--results", type=Path, required=True)
    score.add_argument("--reviews", type=Path, required=True)
    for command in (run, score):
        command.add_argument("--output-dir", type=Path, required=True)
        command.add_argument("--pricing", type=Path)
    args = parser.parse_args(argv)
    reasoners = {}
    try:
        # Detect overwrite mistakes before paid model work.
        if any((args.output_dir / name).exists() for name in ("results.json", "summary.md", "review-template.json")):
            raise ValueError("Output artifacts already exist; choose a new output directory")
        pricing = load_pricing(args.pricing) if args.pricing else None
        if args.command == "run":
            dataset = load_dataset(args.dataset)
            reasoners = configured_reasoners(args.provider)
            report = score_report(run_evaluation(dataset, reasoners), pricing=pricing)
        else:
            results = read_json(args.results)
            reviews = ReviewFile.model_validate(read_json(args.reviews))
            report = score_report(results, reviews=reviews, pricing=pricing)
        write_reports(report, args.output_dir)
        errors = report["scoring"]["metrics"]["overall"]["provider_errors"]
        print(f"Wrote {len(report['cases'])} cases to {args.output_dir}; {errors} provider errors; reviews {report['scoring']['review_status']}.")
        return 1 if errors else 0
    except ValidationError as exc:
        locations = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors(include_input=False))
        print(f"Invalid evaluation/review/pricing data at: {locations}", file=sys.stderr)
        return 2
    except (ResolutionError, OSError, ValueError, KeyError, TypeError) as exc:
        # Internal error text and data values may contain secrets. Only deliberate
        # validation messages are exposed, never arbitrary file/provider bodies.
        message = str(exc) if type(exc) is ValueError else "Evaluation input could not be read, validated, or written."
        print(message, file=sys.stderr)
        return 2
    finally:
        close_reasoners(reasoners)


if __name__ == "__main__":
    raise SystemExit(main())
