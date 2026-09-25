from fastapi.testclient import TestClient

from app.main import create_app
from app.reasoner import RuleBasedReasoner


def test_demo_page_and_local_assets_are_served():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        page = client.get("/demo")
        css = client.get("/demo/assets/styles.css")
        javascript = client.get("/demo/assets/app.js")

    assert page.status_code == css.status_code == javascript.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Guided business demonstration" in page.text
    assert "Analyse exception" in page.text
    assert "Architecture &amp; real-world path" in page.text
    assert "Demo today" in page.text and "Enterprise target" in page.text
    assert "Target operating process" in page.text
    assert "Policy engine decides the route" in page.text
    assert "immutable audit" in page.text
    assert "Authority boundary" in page.text
    assert "APIs, RPA, and agents working as one system" in page.text
    assert "REST tools" in page.text and "RPA workers" in page.text and "Agent capabilities" in page.text
    assert "Human approval" in page.text and "Deterministic execution layer" in page.text
    assert "API action handlers" in page.text and "RPA action workers" in page.text
    assert 'src="/demo/assets/app.js"' in page.text
    assert 'href="/demo/assets/styles.css"' in page.text
    assert "http://" not in page.text and "https://" not in page.text


def test_demo_status_is_sanitized_and_reports_runtime_modes(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "SECRET-not-for-ui")
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.get("/demo/status")
    assert response.status_code == 200
    assert response.json() == {
        "version": "0.4.0",
        "reasoner_provider": "rule_based",
        "connector_mode": "fixture",
        "action_mode": "record_only",
    }
    assert "SECRET" not in response.text
    assert "base_url" not in response.text and "deployment" not in response.text


def test_demo_status_reports_http_connector_without_exposing_urls(monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "http")
    monkeypatch.setenv("ERP_BASE_URL", "https://erp.secret.example")
    monkeypatch.setenv("LOGISTICS_BASE_URL", "https://logistics.secret.example")
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.get("/demo/status")
    assert response.status_code == 200
    assert response.json()["connector_mode"] == "http"
    assert "secret.example" not in response.text


def test_demo_assets_are_accessible_and_render_untrusted_values_as_text():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        page = client.get("/demo").text
        javascript = client.get("/demo/assets/app.js").text
        css = client.get("/demo/assets/styles.css").text

    assert 'role="tablist"' in page
    assert 'aria-live="polite"' in page
    assert 'class="skip-link"' in page
    assert "ArrowLeft" in javascript and "ArrowRight" in javascript
    assert ".textContent" in javascript
    assert "innerHTML" not in javascript
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css


def test_demo_javascript_handles_safe_errors_and_exact_action_replay():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        javascript = client.get("/demo/assets/app.js").text
    for code in (
        "missing_evidence", "connector_bad_response", "invalid_provider_output",
        "connector_unavailable", "connector_circuit_open", "provider_unavailable",
        "connector_timeout", "provider_timeout",
    ):
        assert code in javascript
    assert "Object.freeze" in javascript
    assert '"Idempotency-Key": state.actionKey' in javascript
    assert "JSON.stringify(state.actionPayload)" in javascript
    assert 'response.headers.get("X-Run-ID")' in javascript


def test_guided_api_sequence_resolves_records_and_replays_same_action():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        resolution = client.post("/exceptions/EX-001/resolve")
        assert resolution.status_code == 200
        recommendation = resolution.json()
        payload = {
            "exception_id": recommendation["exception_id"],
            "document_type": "commercial_invoice",
            "reason": recommendation["recommended_action"],
        }
        headers = {"Idempotency-Key": "guided-demo-test-key"}
        first = client.post("/actions/request-document", json=payload, headers=headers)
        replay = client.post("/actions/request-document", json=payload, headers=headers)

    assert first.status_code == replay.status_code == 202
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert first.json() == replay.json()
