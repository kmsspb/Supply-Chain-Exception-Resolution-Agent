import json

import httpx
import pytest
from openai import OpenAI

from app import config, repository
from app.audit import clear_events
from app.azure_reasoner import AzureOpenAIReasoner
from app.config import Settings
from app.context import build_context


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch, tmp_path):
    for name in (
        "REASONER_PROVIDER", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_TIMEOUT_SECONDS", "AZURE_OPENAI_MAX_OUTPUT_TOKENS",
        "CONNECTOR_MODE", "ERP_BASE_URL", "LOGISTICS_BASE_URL",
        "CONNECTOR_CONNECT_TIMEOUT_SECONDS", "CONNECTOR_READ_TIMEOUT_SECONDS",
        "CONNECTOR_WRITE_TIMEOUT_SECONDS", "CONNECTOR_POOL_TIMEOUT_SECONDS",
        "CONNECTOR_ATTEMPTS", "CONNECTOR_BREAKER_THRESHOLD", "CONNECTOR_BREAKER_OPEN_SECONDS",
        "ACTION_DB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    clear_events()
    yield
    clear_events()


@pytest.fixture
def context():
    return build_context(
        repository.get_exception("EX-001"), repository.get_order("SO-1001"),
        repository.get_shipment("SHP-9001"), repository.get_note("SHP-9001"),
    )


@pytest.fixture
def draft(context):
    return {
        "category": "customs_documentation", "summary": "The invoice is incomplete.",
        "recommended_action": "Request the corrected invoice.", "confidence": 0.91,
        "risk_level": "medium", "human_approval_required": True,
        "cause_evidence_ids": [context.evidence[2].evidence_id],
        "action_evidence_ids": [context.evidence[2].evidence_id],
    }


@pytest.fixture
def azure_factory(draft):
    clients = []

    def create(payload=None, *, status="completed", refusal=False, text=None, http_status=200, failure=None):
        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            if failure:
                raise failure(request)
            if http_status != 200:
                return httpx.Response(http_status, json={"error": {"message": "SECRET-test-key upstream body"}})
            content = (
                [{"type": "refusal", "refusal": "SECRET-test-key refusal text"}]
                if refusal else [{"type": "output_text", "annotations": [], "text": text if text is not None else json.dumps(payload if payload is not None else draft)}]
            )
            return httpx.Response(200, json={
                "id": "resp_test", "object": "response", "created_at": 1780000000,
                "status": status, "model": "returned-model-version",
                "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed", "content": content}],
                "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
            })

        settings = Settings(
            provider="azure_openai", base_url="https://example.openai.azure.com/openai/v1/",
            api_key="SECRET-test-key", deployment="test-deployment",
        )
        client = OpenAI(
            base_url=settings.base_url, api_key=settings.api_key, max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        clients.append(client)
        return AzureOpenAIReasoner(settings, client=client), requests

    yield create
    for client in clients:
        client.close()
