import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import repository, tools
from app.audit import get_events
from app.errors import (
    ConfigurationError, CorruptData, ExceptionNotFound, InvalidProviderOutput,
    MissingEvidence, ProviderRefusal, ProviderTimeout, ProviderUnavailable,
)
from app.main import create_app
from app.reasoner import RuleBasedReasoner
from app.service import resolve_exception


def test_existing_routes_and_run_filter():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        assert client.get("/health").json() == {"status": "ok"}
        first = client.post("/exceptions/EX-001/resolve")
        second = client.post("/exceptions/EX-001/resolve")
        assert first.status_code == second.status_code == 200
        result = first.json()
        run_id = result["run_id"]
        assert first.headers["X-Run-ID"] == run_id
        assert run_id != second.json()["run_id"]
        assert result["category"] == "customs_documentation"
        assert result["confidence"] == 0.93
        assert result["provider"] == "rule_based"
        assert len(result["evidence"]) == 3
        events = client.get(f"/exceptions/EX-001/audit?run_id={run_id}").json()["events"]
        assert {event["run_id"] for event in events} == {run_id}
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert events[0]["event_type"] == "resolution_started"
        assert events[-1]["event_type"] == "resolution_completed"
        completed = [event["details"]["tool"] for event in events if event["event_type"] == "connector_completed"]
        assert completed == ["get_erp_order", "get_logistics_status", "get_shipment_note"]
        assert all("elapsed_ms" in event["details"] for event in events if event["event_type"] == "connector_completed")
        schema = client.get("/openapi.json").json()
        assert schema["info"]["version"] == "0.2.0"
        assert "ResolutionRecommendation" in schema["paths"]["/exceptions/{exception_id}/resolve"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]


def test_missing_exception_is_traced_before_lookup():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.post("/exceptions/does-not-exist/resolve")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "exception_not_found"
    assert response.headers["X-Run-ID"] == detail["run_id"]
    events = get_events(run_id=detail["run_id"])
    assert [event["event_type"] for event in events] == ["resolution_started", "resolution_failed"]


@pytest.mark.parametrize("error,status", [
    (InvalidProviderOutput, 502), (ProviderRefusal, 502),
    (ProviderUnavailable, 503), (ProviderTimeout, 504),
])
def test_provider_errors_have_safe_correlated_responses(error, status):
    class FailingReasoner(RuleBasedReasoner):
        provider = "azure_openai"

        def resolve(self, context):
            raise error()

    with TestClient(create_app(FailingReasoner())) as client:
        response = client.post("/exceptions/EX-001/resolve")
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == error.code
    assert detail["run_id"] == response.headers["X-Run-ID"]
    assert get_events(run_id=detail["run_id"])[-1]["event_type"] == "resolution_failed"


def test_missing_supporting_evidence_is_422(monkeypatch):
    monkeypatch.setattr(repository, "get_note", lambda shipment_id: None)
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.post("/exceptions/EX-001/resolve")
    assert response.status_code == 422
    events = get_events(run_id=response.headers["X-Run-ID"])
    assert events[-2]["event_type"] == "connector_failed"
    assert events[-2]["details"]["tool"] == "get_shipment_note"
    assert not any(event["event_type"] == "model_invoked" for event in events)


@pytest.mark.parametrize("content", ["not json", "{}", '[{"exception_id": 42}]', '[{"exception_id":"EX-001"}]'])
def test_corrupt_local_data_is_500(monkeypatch, tmp_path, content):
    (tmp_path / "exceptions.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(repository, "DATA_DIR", tmp_path)
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.post("/exceptions/EX-001/resolve")
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "corrupt_local_data"
    assert response.headers["X-Run-ID"]


def test_invalid_relationship_fails_before_model(monkeypatch):
    original = repository.get_note("SHP-9001")
    monkeypatch.setattr(repository, "get_note", lambda shipment_id: {**original, "shipment_id": "OTHER"})
    with pytest.raises(CorruptData):
        resolve_exception("EX-001")
    assert not any(event["event_type"] == "model_invoked" for event in get_events())


def test_unexpected_connector_error_is_sanitized(monkeypatch):
    def broken(record_id):
        raise RuntimeError("SECRET-from-connector")

    monkeypatch.setattr(tools, "get_erp_order", broken)
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.post("/exceptions/EX-001/resolve")
    assert response.status_code == 500
    assert "SECRET-from-connector" not in response.text + json.dumps(get_events())


def test_startup_validates_selected_provider(monkeypatch):
    monkeypatch.setenv("REASONER_PROVIDER", "azure_openai")
    with pytest.raises(ConfigurationError):
        with TestClient(create_app()):
            pass
    monkeypatch.setenv("REASONER_PROVIDER", "rule_based")
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


def test_concurrent_runs_are_isolated_and_snapshots_are_defensive():
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: resolve_exception("EX-001", RuleBasedReasoner()), range(12)))
    assert len({result.run_id for result in results}) == 12
    for result in results:
        events = get_events(run_id=result.run_id)
        assert {event["run_id"] for event in events} == {result.run_id}
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        assert events[-1]["event_type"] == "resolution_completed"
        events[-1]["details"]["provider"] = "tampered"
        assert get_events(run_id=result.run_id)[-1]["details"]["provider"] == "rule_based"
