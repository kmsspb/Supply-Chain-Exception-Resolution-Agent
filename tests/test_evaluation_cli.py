import json

from app.evaluate import main
from app.evaluation.dataset import load_dataset
from app.evaluation.reporting import render_summary
from app.evaluation.runner import run_evaluation, score_report
from app.errors import ProviderUnavailable
from app.reasoner import RuleBasedReasoner


def test_run_and_score_cli_without_model_calls(tmp_path, monkeypatch):
    output = tmp_path / "baseline"
    assert main(["run", "--output-dir", str(output)]) == 0
    assert {path.name for path in output.iterdir()} == {"results.json", "summary.md", "review-template.json"}
    report = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(report["cases"]) == 30
    assert report["scoring"]["review_status"] == "pending"
    text = (output / "summary.md").read_text(encoding="utf-8")
    assert "not available" in text and "0 reviewed" in text

    def forbidden(*args, **kwargs):
        raise AssertionError("Score must not instantiate or invoke a provider")

    monkeypatch.setattr("app.evaluate.configured_reasoners", forbidden)
    scored = tmp_path / "scored"
    assert main(["score", "--results", str(output / "results.json"), "--reviews", str(output / "review-template.json"), "--output-dir", str(scored)]) == 0
    refreshed = json.loads((scored / "results.json").read_text(encoding="utf-8"))
    assert refreshed["scoring"]["metrics"] == report["scoring"]["metrics"]
    assert refreshed["results_hash"] == report["results_hash"]
    assert main(["run", "--output-dir", str(output)]) == 2  # No overwrite or paid work.


def test_both_cli_preserves_missing_configuration_errors(tmp_path):
    output = tmp_path / "both"
    assert main(["run", "--provider", "both", "--output-dir", str(output)]) == 1
    report = json.loads((output / "results.json").read_text(encoding="utf-8"))
    baseline = report["scoring"]["metrics"]["providers"]["rule_based"]["overall"]
    azure = report["scoring"]["metrics"]["providers"]["azure_openai"]["overall"]
    assert baseline["successful_outputs"] == 30
    assert azure["provider_errors"] == 30
    assert azure["classification"]["attempt_accuracy"] == 0
    assert azure["classification"]["successful_output_accuracy"] is None
    assert azure["actions"]["coverage"] is None
    assert azure["cost"]["total"] is None
    assert azure["cost"]["unavailable_runs"] == 30


def test_failed_provider_has_no_fallback_or_fake_complete_reviews():
    class Failed(RuleBasedReasoner):
        provider = "azure_openai"

        def resolve(self, context):
            raise ProviderUnavailable()

    report = score_report(run_evaluation(load_dataset(), {"azure_openai": Failed()}))
    assert report["scoring"]["review_status"] == "no_successful_outputs"
    assert all("recommendation" not in case["results"]["azure_openai"] for case in report["cases"])
    assert "not available" in render_summary(report)


def test_missing_inputs_fail_cleanly(tmp_path, capsys):
    assert main(["score", "--results", str(tmp_path / "missing"), "--reviews", str(tmp_path / "reviews"), "--output-dir", str(tmp_path / "out")]) == 2
    assert "Traceback" not in capsys.readouterr().err
