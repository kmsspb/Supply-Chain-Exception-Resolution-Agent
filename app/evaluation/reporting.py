import html
import json
from pathlib import Path

from app.evaluation.reviews import review_template


def _cell(value):
    return html.escape(str(value)).replace("|", "\\|").replace("\n", " ")


def _number(value):
    return "not available" if value is None else f"{value:.3f}"


def _percent(value):
    return "not available" if value is None else f"{value:.1%}"


def _quality_row(label, metric):
    return "| " + " | ".join(map(_cell, [
        label, f"{metric['successful_outputs']}/{metric['attempts']}",
        _percent(metric["classification"]["attempt_accuracy"]),
        f"{_percent(metric['actions']['accuracy'])} ({metric['actions']['reviewed']} reviewed)",
        f"{_percent(metric['claims']['unsupported_claim_rate'])} ({metric['claims']['reviewed_outputs']} outputs reviewed)",
        f"{_percent(metric['escalation']['accuracy'])} ({metric['escalation']['reviewed']} reviewed)",
    ])) + " |"


def render_summary(report: dict) -> str:
    scoring, dataset = report["scoring"], report["dataset"]
    lines = [
        "# Supply-chain evaluation — v0.3", "",
        f"Dataset: **{_cell(dataset['name'])} {dataset['version']}**; {len(dataset['cases'])} cases.",
        f"Created: {report['created_at']}. Review status: **{scoring['review_status']}**.",
        f"Dataset hash: `{report['dataset_hash']}`. Results hash: `{report['results_hash']}`.", "",
        "This report measures fixed reasoners. Semantic scores require actual human review; no model judge or fabricated human judgements are used.",
        "Provider errors count against all-attempt classification accuracy. Action, claim, and escalation scores use reviewed successful outputs only; coverage is reported separately.",
        "An unreviewed metric is not available, not zero and not a pass. A completed run is not a quality release gate.", "",
        "## Quality and review coverage", "",
        "| Provider / slice | Outputs / attempts | Classification, all attempts | Correct action | Unsupported claims | Escalation accuracy |",
        "| --- | --- | --- | --- | --- | --- |",
        _quality_row("All providers", scoring["metrics"]["overall"]),
    ]
    for provider, groups in scoring["metrics"]["providers"].items():
        lines.append(_quality_row(provider, groups["overall"]))
        lines.append(_quality_row(f"{provider}: 24 new cases", groups["new_cases"]))
        for family, metric in groups["families"].items():
            lines.append(_quality_row(f"{provider}: {family}", metric))
    for provider, groups in scoring["metrics"]["providers"].items():
        metric = groups["overall"]
        lines += ["", f"## {_cell(provider)} details", "",
                  f"Classification among successful outputs: {_percent(metric['classification']['successful_output_accuracy'])}.",
                  f"Action review coverage: {_percent(metric['actions']['coverage'])}; claim review coverage: {_percent(metric['claims']['coverage'])}; escalation review coverage: {_percent(metric['escalation']['coverage'])}.",
                  f"Claim verdicts: {metric['claims']['supported']} supported, {metric['claims']['unsupported']} unsupported, {metric['claims']['uncertain']} uncertain. Uncertainty rate: {_percent(metric['claims']['uncertainty_rate'])}.",
                  f"Escalation precision: {_percent(metric['escalation']['precision'])}; recall: {_percent(metric['escalation']['recall'])}.",
                  f"Citation integrity: {metric['citations']['valid_outputs']}/{metric['citations']['checked_outputs']} outputs. This does not establish factual support.", "",
                  "| Timing (milliseconds) | Count | Mean | Median | p95 |", "| --- | --- | --- | --- | --- |"]
        for status, kinds in metric["latency"].items():
            for kind, stats in kinds.items():
                lines.append(f"| {status} / {kind} | {stats['count']} | {_number(stats['mean_ms'])} | {_number(stats['median_ms'])} | {_number(stats['p95_ms'])} |")
        lines += ["", "Analysis timing excludes fixture loading and the application's HTTP layer. Provider timing measures the reasoner invocation stage, including failures; p95 uses nearest rank on this small sample.", "",
                  "| Token kind | Known subtotal | Runs with known usage | Coverage |", "| --- | --- | --- | --- |"]
        for key, usage in metric["tokens"].items():
            lines.append(f"| {key} | {usage['known_subtotal'] if usage['known_subtotal'] is not None else 'not available'} | {usage['known_runs']} | {_percent(usage['coverage'])} |")
        cost = metric["cost"]
        lines += ["", f"Cost coverage: {_percent(cost['coverage'])}; unavailable runs: {cost['unavailable_runs']}; zero-model-cost runs: {cost['zero_model_cost_runs']}."]
        if cost["total"] is not None:
            lines.append(f"Estimated total model cost: {cost['total']['amount']} {cost['total']['currency'] or '(no model charges)'}.")
        else:
            lines.append("Total model cost: **not available**. Unknown usage is not free; different currencies are not added together.")
        for currency, amount in cost["known_subtotals"].items():
            lines.append(f"Known subtotal: {amount} {currency}.")
        for reason, count in cost["unavailable_reasons"].items():
            lines.append(f"Unavailable: {reason} ({count} runs).")
    lines += ["", "Cost estimates use the supplied pricing snapshot and exclude infrastructure, taxes, and other billing items. Reasoning tokens are already included in output tokens and are not charged a second time.",
              "", "## Case outcomes", "", "| Case | Origin | Provider | Expected category | Actual category / error | Run ID |", "| --- | --- | --- | --- | --- | --- |"]
    for case in report["cases"]:
        for provider, result in case["results"].items():
            actual = result["recommendation"]["category"] if result["status"] == "success" else result["error"]["code"]
            lines.append("| " + " | ".join(_cell(x) for x in (case["case_id"], case["origin"], provider, case["expected"]["category"], actual, result["run_id"])) + " |")
    lines += ["", "## Review instructions", "",
              "Use results.json for each case's evidence, recommendation, expected action criteria, prohibited actions/claims, and rationale. Copy review-template.json to reviews.json and edit only judgements you actually review.",
              "Provide reviewer identity, a timezone-aware timestamp, and rationale. Mark action correctness and whether manual investigation was recommended independently of the approval flag.",
              "Quote each factual assertion from category, summary, or recommended_action; mark it supported, unsupported, or uncertain, explaining the judgement and citing source evidence IDs. Proposals are not claims that an action was executed.",
              "Mark claims_complete only after reviewing all factual assertions. Partial claim reviews remain outside claim-rate denominators. This completeness declaration is the reviewer's responsibility; the software cannot prove semantic completeness.",
              "Run the score command to import reviews without making model calls. Full confusion counts, per-family timings/usage, pricing snapshots, review provenance, and per-run costs are in results.json.", ""]
    return "\n".join(lines)


def write_reports(report: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "results.json": json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        "summary.md": render_summary(report),
        "review-template.json": json.dumps(review_template(report).model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
    }
    # Do not overwrite existing results or a review template someone may be editing.
    if any((output_dir / name).exists() for name in artifacts):
        raise ValueError("Output artifacts already exist; choose a new output directory")
    for name, content in artifacts.items():
        (output_dir / name).write_text(content, encoding="utf-8")
