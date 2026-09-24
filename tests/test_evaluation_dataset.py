from collections import Counter
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.compare import load_cases
from app.evaluate import main
from app.evaluation.dataset import EvaluationDataset, FAMILIES, load_dataset
from app.evaluation.runner import run_evaluation, validate_results
from app.reasoner import RuleBasedReasoner


def test_dataset_balance_and_original_seeds():
    dataset = load_dataset()
    assert len(dataset.cases) == 30
    assert Counter(case.family for case in dataset.cases) == {family: 5 for family in FAMILIES}
    assert Counter(case.origin for case in dataset.cases) == {"seed": 6, "new": 24}
    seeds = {case.case_id: case for case in dataset.cases if case.origin == "seed"}
    for original in load_cases():
        seed = seeds[original["case_id"]]
        assert seed.context() == original["context"]
        assert seed.expected.category == original["expected"]["category"]
        assert seed.expected.manual_escalation == original["expected"]["manual_escalation"]
    assert len({case.note["text"] for case in dataset.cases}) == 30


@pytest.mark.parametrize("mutation", [
    lambda data: data["cases"].pop(),
    lambda data: data["cases"].__setitem__(1, deepcopy(data["cases"][0])),
    lambda data: data["cases"][0].__setitem__("family", "weather_delays"),
    lambda data: data["cases"][0].__setitem__("origin", "new"),
    lambda data: data["cases"][0]["expected"].__setitem__("category", "typo"),
    lambda data: data["cases"][0]["expected"].__setitem__("supporting_evidence_ids", ["invented:1"]),
    lambda data: data["cases"][0]["expected"].__setitem__("manual_escalation", "false"),
    lambda data: data["cases"][0]["note"].__setitem__("shipment_id", "OTHER"),
    lambda data: data["cases"][0]["expected"].__setitem__("acceptable_action_criteria", []),
])
def test_invalid_dataset_rejected(mutation):
    data = load_dataset().model_dump(mode="json")
    mutation(data)
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(data)


def test_dataset_validation_precedes_provider_setup(tmp_path, monkeypatch):
    source = tmp_path / "invalid.json"
    source.write_text("{}", encoding="utf-8")

    def forbidden(*args):
        raise AssertionError("Provider must not be constructed for invalid data")

    monkeypatch.setattr("app.evaluate.configured_reasoners", forbidden)
    assert main(["run", "--dataset", str(source), "--output-dir", str(tmp_path / "report")]) == 2


def test_same_context_without_annotations_is_used_by_both_providers():
    observed = {"rule_based": [], "azure_openai": []}

    class Observed(RuleBasedReasoner):
        def __init__(self, provider):
            self.provider = provider

        def resolve(self, context):
            observed[self.provider].append(context)
            assert set(context.model_dump()) == {"exception", "order", "shipment", "note", "evidence"}
            assert "acceptable_action_criteria" not in context.model_dump_json()
            return super().resolve(context)

    report = run_evaluation(load_dataset(), {name: Observed(name) for name in observed})
    assert len(observed["rule_based"]) == 30
    assert all(first is second for first, second in zip(observed["rule_based"], observed["azure_openai"]))
    validate_results(report)
    assert len({result["run_id"] for case in report["cases"] for result in case["results"].values()}) == 60
