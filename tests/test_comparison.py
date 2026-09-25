import json

from app.compare import load_cases, main, run_comparison
from app.reasoner import RuleBasedReasoner


def test_six_cases_and_baseline_limitations_are_preserved():
    cases = load_cases()
    report = run_comparison(cases, {"rule_based": RuleBasedReasoner()})
    assert len(report["cases"]) == 6
    assert all(case["results"]["rule_based"]["status"] == "success" for case in report["cases"])
    categories = [case["results"]["rule_based"]["recommendation"]["category"] for case in report["cases"]]
    assert categories == [
        "customs_documentation", "customs_documentation", "weather_delay",
        "unknown_logistics_exception", "customs_documentation", "customs_documentation",
    ]
    assert report["cases"][1]["expected"]["category"] == "customs_cleared"


def test_comparison_reuses_identical_context_and_records_usage(azure_factory, draft):
    case = load_cases()[0]
    azure, requests = azure_factory()
    observed = []

    class ObservedBaseline(RuleBasedReasoner):
        def resolve(self, context):
            observed.append(context)
            return super().resolve(context)

    report = run_comparison([case], {"rule_based": ObservedBaseline(), "azure_openai": azure})
    assert observed[0] is case["context"]
    assert json.loads(requests[0]["input"]) == observed[0].model_dump(mode="json")
    results = report["cases"][0]["results"]
    assert results["azure_openai"]["metadata"]["usage"]["total_tokens"] == 140
    assert results["azure_openai"]["run_id"] != results["rule_based"]["run_id"]
    assert all(result["elapsed_ms"] >= 0 for result in results.values())


def test_comparison_reports_azure_failure_without_fallback(azure_factory):
    azure, requests = azure_factory(http_status=429)
    report = run_comparison(load_cases(), {"rule_based": RuleBasedReasoner(), "azure_openai": azure})
    assert len(requests) == 6
    for case in report["cases"]:
        result = case["results"]["azure_openai"]
        assert result["status"] == "error"
        assert result["error"]["code"] == "provider_unavailable"
        assert "recommendation" not in result
        assert result["trace"][-1]["event_type"] == "resolution_failed"
        assert case["results"]["rule_based"]["status"] == "success"
    assert "SECRET-test-key" not in json.dumps(report)


def test_cli_baseline_and_missing_azure_configuration(tmp_path):
    output = tmp_path / "baseline.json"
    assert main(["--provider", "rule_based", "--output", str(output)]) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))["cases"]) == 6
    output = tmp_path / "both.json"
    assert main(["--provider", "both", "--output", str(output)]) == 1
    for case in json.loads(output.read_text(encoding="utf-8"))["cases"]:
        assert case["results"]["azure_openai"]["error"]["code"] == "provider_configuration_error"
        assert case["results"]["rule_based"]["status"] == "success"
