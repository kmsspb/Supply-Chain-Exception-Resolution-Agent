import json

import httpx
import pytest

from app.audit import get_events
from app.azure_reasoner import PROMPT, PROMPT_VERSION
from app.errors import (
    IncompleteProviderOutput, InvalidProviderOutput, ProviderRefusal,
    ProviderTimeout, ProviderUnavailable,
)
from app.models import ProviderRecommendation
from app.service import analyse_context


def test_sdk_parsing_and_grounded_public_evidence(azure_factory, context):
    reasoner, requests = azure_factory()
    result = analyse_context(context, reasoner)
    assert result.provider == "azure_openai"
    assert result.evidence == [context.evidence[2]]
    assert result.evidence[0].fact == context.evidence[2].fact
    request = requests[0]
    assert request["model"] == "test-deployment"
    assert request["instructions"] == PROMPT
    assert json.loads(request["input"]) == context.model_dump(mode="json")
    assert request["max_output_tokens"] == 4096
    assert request["store"] is False
    assert request["text"]["format"]["strict"] is True
    events = get_events(run_id=result.run_id)
    invocation = next(e for e in events if e["event_type"] == "model_invoked")
    assert invocation["details"]["prompt_version"] == PROMPT_VERSION
    assert len(invocation["details"]["prompt_hash"]) == 64
    metadata = next(e for e in events if e["event_type"] == "model_completed")["details"]["metadata"]
    assert metadata["model"] == "returned-model-version"
    assert metadata["response_id"] == "resp_test"
    assert metadata["usage"]["total_tokens"] == 140
    assert "SECRET-test-key" not in json.dumps(events)


def test_provider_schema_matches_azure_subset():
    schema = ProviderRecommendation.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    forbidden = {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "default"}

    def walk(node):
        if isinstance(node, dict):
            assert not forbidden.intersection(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


@pytest.mark.parametrize("field,value", [
    ("confidence", 1.1), ("confidence", -0.1), ("confidence", float("nan")),
    ("confidence", float("inf")), ("summary", " "), ("category", ""),
    ("recommended_action", "\n"), ("cause_evidence_ids", []),
    ("action_evidence_ids", []), ("cause_evidence_ids", ["invented:123"]),
    ("action_evidence_ids", ["note:OTHER"]), ("risk_level", "catastrophic"),
    ("evidence", [{"fact": "invented"}]),
])
def test_invalid_output_is_rejected_without_baseline(azure_factory, context, draft, field, value):
    draft[field] = value
    reasoner, requests = azure_factory(draft)
    with pytest.raises(InvalidProviderOutput) as caught:
        analyse_context(context, reasoner)
    events = get_events(run_id=caught.value.run_id)
    assert events[-1]["event_type"] == "resolution_failed"
    assert any(e["event_type"] == "output_validation_failed" for e in events)
    assert not any(e["event_type"] == "recommendation_created" for e in events)
    assert len(requests) == 1


@pytest.mark.parametrize("options,error", [
    ({"refusal": True}, ProviderRefusal),
    ({"status": "incomplete"}, IncompleteProviderOutput),
    ({"text": "not JSON"}, InvalidProviderOutput),
    ({"text": "{}"}, InvalidProviderOutput),
    ({"http_status": 401}, ProviderUnavailable),
    ({"http_status": 429}, ProviderUnavailable),
    ({"http_status": 503}, ProviderUnavailable),
])
def test_provider_failures_are_safe(azure_factory, context, options, error):
    reasoner, requests = azure_factory(**options)
    with pytest.raises(error) as caught:
        analyse_context(context, reasoner)
    assert caught.value.run_id
    events = get_events(run_id=caught.value.run_id)
    assert "SECRET-test-key" not in json.dumps(events)
    assert "SECRET-test-key" not in str(caught.value)
    assert len(requests) == 1


def test_timeout(azure_factory, context):
    reasoner, requests = azure_factory(failure=lambda request: httpx.ReadTimeout("SECRET-test-key", request=request))
    with pytest.raises(ProviderTimeout):
        analyse_context(context, reasoner)
    assert len(requests) == 1
    assert "SECRET-test-key" not in json.dumps(get_events())
