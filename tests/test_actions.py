import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.actions import ActionStore
from app.audit import get_events
from app.connectors.factory import create_connector_bundle
from app.main import create_app
from app.reasoner import RuleBasedReasoner

PAYLOAD = {
    "exception_id": "EX-001", "document_type": "commercial_invoice",
    "reason": "Customs requires a corrected invoice",
}


def app_client(path):
    return TestClient(create_app(
        RuleBasedReasoner(), create_connector_bundle().tools, ActionStore(path),
    ))


def test_action_record_replay_restart_lookup_and_no_external_effect(tmp_path):
    path = tmp_path / "actions.sqlite3"
    with app_client(path) as client:
        first = client.post("/actions/request-document", json=PAYLOAD, headers={"Idempotency-Key": "request-123"})
        assert first.status_code == 202
        assert first.headers["Idempotency-Replayed"] == "false"
        record = first.json()
        assert record["status"] == "recorded"
        assert client.get(f"/actions/{record['action_id']}").json() == record
    with app_client(path) as client:
        replay = client.post("/actions/request-document", json=PAYLOAD, headers={"Idempotency-Key": "request-123"})
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == record
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT idempotency_key_hash, status, COUNT(*) FROM action_intents").fetchone()
    assert row[0] != "request-123" and len(row[0]) == 64
    assert row[1:] == ("recorded", 1)
    assert [event["event_type"] for event in get_events("EX-001") if event["event_type"].startswith("action_intent_")] == [
        "action_intent_recorded", "action_intent_replayed",
    ]


def test_conflict_is_409_and_trace_has_hash_only(tmp_path):
    with app_client(tmp_path / "actions.sqlite3") as client:
        assert client.post("/actions/request-document", json=PAYLOAD, headers={"Idempotency-Key": "request-123"}).status_code == 202
        response = client.post(
            "/actions/request-document", json={**PAYLOAD, "reason": "Different"},
            headers={"Idempotency-Key": "request-123"},
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    conflicts = [event for event in get_events("EX-001") if event["event_type"] == "action_intent_conflict"]
    assert len(conflicts) == 1
    assert "request-123" not in repr(conflicts)
    assert len(conflicts[0]["details"]["idempotency_key_hash"]) == 64


@pytest.mark.parametrize("key", [None, "short", "has space", "line\nbreak", "x" * 129])
def test_invalid_idempotency_keys_are_400(tmp_path, key):
    headers = {} if key is None else {"Idempotency-Key": key}
    with app_client(tmp_path / "actions.sqlite3") as client:
        response = client.post("/actions/request-document", json=PAYLOAD, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_idempotency_key"


def test_connector_failure_inserts_no_row_and_same_key_can_retry(tmp_path, monkeypatch):
    path = tmp_path / "actions.sqlite3"
    bundle = create_connector_bundle()
    original = bundle.tools.get_shipment_note
    monkeypatch.setattr(bundle.tools, "get_shipment_note", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")))
    with TestClient(create_app(RuleBasedReasoner(), bundle.tools, ActionStore(path))) as client:
        failed = client.post("/actions/request-document", json=PAYLOAD, headers={"Idempotency-Key": "request-123"})
    assert failed.status_code == 500
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM action_intents").fetchone()[0] == 0
    monkeypatch.setattr(bundle.tools, "get_shipment_note", original)
    with TestClient(create_app(RuleBasedReasoner(), bundle.tools, ActionStore(path))) as client:
        assert client.post("/actions/request-document", json=PAYLOAD, headers={"Idempotency-Key": "request-123"}).status_code == 202


def test_concurrent_identical_requests_create_one_row(tmp_path):
    path = tmp_path / "actions.sqlite3"
    store = ActionStore(path)
    tools = create_connector_bundle().tools

    def submit(_):
        with TestClient(create_app(RuleBasedReasoner(), tools, store)) as client:
            response = client.post("/actions/request-document", json=PAYLOAD, headers={"Idempotency-Key": "concurrent-key"})
            return response.status_code, response.json()["action_id"]

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(submit, range(12)))
    assert {status for status, _ in results} == {202}
    assert len({action_id for _, action_id in results}) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM action_intents").fetchone()[0] == 1


def test_unknown_action_is_404(tmp_path):
    with app_client(tmp_path / "actions.sqlite3") as client:
        response = client.get("/actions/unknown")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "action_not_found"
