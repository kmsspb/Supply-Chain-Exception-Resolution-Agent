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
    assert "Corrected commercial invoice awaited" in page.text
    assert "Delivery at risk" in page.text
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
    assert "http://" not in page.text
    assert page.text.count("https://github.com/kmsspb/Supply-Chain-Exception-Resolution-Agent") == 4
    assert page.text.index('id="analyse-button"') < page.text.index('class="progress-steps"')
    assert 'id="case-select"' in page.text
    assert 'id="reasoning-chain"' in page.text
    assert 'aria-label="Workflow overview"' in page.text
    assert 'aria-label="Demo progress"' not in page.text
    assert "Detailed target process and technical contracts" in page.text
    assert "Independent synthetic portfolio exercise" in page.text


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
        page = client.get("/demo").text
        css = client.get("/demo/assets/styles.css").text
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
    assert "recommendation.action_proposal.document_type" in javascript
    assert "/invoice/i" not in javascript
    assert "Reasoner confidence · uncalibrated" in page
    assert "Record proposed action" in page
    assert "Human approval and execution exist only in the target architecture" in page
    assert "state.exceptionId" in javascript
    assert "/exceptions/EX-001/resolve" not in javascript
    assert "evidence-field-highlight" in javascript
    assert "tag.href" in javascript
    assert "See target architecture" in javascript
    assert 'activeButton.setAttribute("aria-busy", "true")' in javascript
    assert 'button:disabled { cursor: not-allowed' in css
    assert 'button[aria-busy="true"]' in css


def test_guided_api_sequence_resolves_records_and_replays_same_action():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        resolution = client.post("/exceptions/EX-001/resolve")
        assert resolution.status_code == 200
        recommendation = resolution.json()
        payload = {
            "exception_id": recommendation["exception_id"],
            "document_type": recommendation["action_proposal"]["document_type"],
            "reason": recommendation["recommended_action"],
        }
        headers = {"Idempotency-Key": "guided-demo-test-key"}
        first = client.post("/actions/request-document", json=payload, headers=headers)
        replay = client.post("/actions/request-document", json=payload, headers=headers)

    assert first.status_code == replay.status_code == 202
    assert first.headers["Idempotency-Replayed"] == "false"
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert first.json() == replay.json()
    assert recommendation["provider"] == "rule_based"
    assert recommendation["action_proposal"] == {
        "action_type": "request_document",
        "document_type": "commercial_invoice",
        "target_system": "document_request_workflow",
        "requires_approval": True,
        "execution_mode": "record_only",
        "supported": True,
    }
    assert first.json()["document_type"] == recommendation["action_proposal"]["document_type"]


def test_demo_copy_distinguishes_recording_approval_and_execution():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        page = client.get("/demo").text
        javascript = client.get("/demo/assets/app.js").text
    assert "Record a proposed action only" in page
    assert "Does not email, approve, dispatch, or update ERP" in page
    assert "Approval and dispatch would be separate production steps" in javascript
    assert "Action intent recorded safely" not in javascript


def test_demo_cases_cover_deterministic_ambiguous_and_fail_closed_routes():
    class MustNotRun:
        provider = "azure_openai"

        def describe(self):
            return {}

        def resolve(self, context):
            raise AssertionError("reasoner must not be called")

    with TestClient(create_app(MustNotRun())) as client:
        catalogue = client.get("/demo/cases")
        deterministic = client.post("/exceptions/EX-002/resolve")
        missing = client.post("/exceptions/EX-004/resolve")

    assert catalogue.status_code == 200
    cases = catalogue.json()["cases"]
    assert [case["exception_id"] for case in cases] == ["EX-001", "EX-002", "EX-003", "EX-004"]
    assert {case["strategy"] for case in cases} == {
        "Configured reasoner", "Deterministic baseline", "No reasoning if evidence is missing",
    }
    assert deterministic.status_code == 200
    assert deterministic.json()["provider"] == "rule_based"
    assert deterministic.json()["category"] == "weather_delay"
    assert deterministic.json()["action_proposal"]["supported"] is False
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "missing_evidence"


def test_ambiguous_case_returns_uncertainty_with_baseline():
    with TestClient(create_app(RuleBasedReasoner())) as client:
        response = client.post("/exceptions/EX-003/resolve")
    assert response.status_code == 200
    result = response.json()
    assert result["category"] == "unknown_logistics_exception"
    assert result["action_proposal"]["action_type"] == "manual_investigation"
    assert result["action_proposal"]["supported"] is False
