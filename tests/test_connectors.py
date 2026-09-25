from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.config import ConnectorSettings
from app.connectors.factory import create_connector_bundle
from app.connectors.http import ResilientHttpReader, retry_after_seconds
from app.connectors.models import ERPOrder
from app.connectors.resilience import Backoff, CircuitBreaker
from app.errors import (
    ConfigurationError, ConnectorBadResponse, ConnectorCircuitOpen,
    ConnectorTimeout, ConnectorUnavailable, MissingEvidence,
)

ORDER = {
    "order_id": "SO-1001", "customer": "Nordic Marine Services",
    "material": "Critical spare part", "quantity": 2,
    "requested_delivery_date": "2026-09-25", "incoterm": "DAP",
    "order_status": "released",
}


def reader(handler, *, attempts=3, threshold=5, sleep=None, clock=None):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    breaker = CircuitBreaker("erp", threshold, 30, clock=clock) if clock else CircuitBreaker("erp", threshold, 30)
    backoff = Backoff(sleep_fn=sleep or (lambda _: None))
    return ResilientHttpReader(client, "erp", breaker, attempts, backoff), client, breaker


def test_fixture_and_http_parity_and_client_shutdown():
    fixture = create_connector_bundle()
    expected = fixture.tools.get_erp_order("SO-1001")
    requested = []

    def handler(request):
        requested.append(request.url.raw_path)
        return httpx.Response(200, json={**ORDER, "order_id": "SO / 1"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = ConnectorSettings(mode="http", erp_base_url="https://erp.test", logistics_base_url="https://log.test")
    bundle = create_connector_bundle(settings, client)
    assert expected == ERPOrder.model_validate(ORDER)
    assert bundle.tools.get_erp_order("SO / 1").order_id == "SO / 1"
    assert requested == [b"/orders/SO%20%2F%201"]
    bundle.close()
    assert client.is_closed


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_each_retryable_status_uses_three_total_attempts(status):
    calls = []
    delays = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    instance, client, _ = reader(handler, sleep=delays.append)
    with client, pytest.raises(ConnectorUnavailable) as caught:
        instance.get("https://erp.test/orders/x", ERPOrder, "order_id", "x")
    assert len(calls) == 3
    assert len(delays) == 2
    assert caught.value.metadata["attempt_count"] == 3
    assert caught.value.metadata["upstream_status"] == status


def test_timeout_retries_and_exhausts_as_504():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("secret", request=request)

    instance, client, _ = reader(handler)
    with client, pytest.raises(ConnectorTimeout):
        instance.get("https://erp.test/orders/x", ERPOrder, "order_id", "x")
    assert calls == 3


@pytest.mark.parametrize("status", [400, 401, 403, 405, 422])
def test_other_client_errors_are_not_retried(status):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    instance, client, _ = reader(handler)
    with client, pytest.raises(ConnectorUnavailable):
        instance.get("https://erp.test/orders/x", ERPOrder, "order_id", "x")
    assert calls == 1


def test_404_maps_to_missing_evidence_and_does_not_open_breaker():
    instance, client, breaker = reader(lambda request: httpx.Response(404), threshold=1)
    with client:
        for _ in range(2):
            with pytest.raises(MissingEvidence):
                instance.get("https://erp.test/orders/x", ERPOrder, "order_id", "x")
    assert breaker.state == "closed"


@pytest.mark.parametrize("payload", [{}, {**ORDER, "quantity": 0}, {**ORDER, "extra": "x"}, {**ORDER, "order_id": "other"}])
def test_schema_and_relationship_failures_are_not_retried(payload):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=payload)

    instance, client, _ = reader(handler)
    with client, pytest.raises(ConnectorBadResponse):
        instance.get("https://erp.test/orders/SO-1001", ERPOrder, "order_id", "SO-1001")
    assert calls == 1


def test_retry_after_is_capped_and_traced_without_response_body():
    calls = 0
    delays = []
    events = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "20"}, text="SECRET body")
        return httpx.Response(200, json=ORDER)

    instance, client, _ = reader(handler, sleep=delays.append)
    with client:
        result = instance.get(
            "https://erp.test/orders/SO-1001", ERPOrder, "order_id", "SO-1001",
            lambda name, details: events.append((name, details)),
        )
    assert result.order_id == "SO-1001"
    assert delays == [5.0]
    assert "SECRET" not in repr(events)
    assert next(details for name, details in events if name == "connector_retry_scheduled")["delay_ms"] == 5000
    assert retry_after_seconds("invalid") is None
    assert retry_after_seconds("nan") is None


def test_circuit_opens_after_failed_logical_calls_and_half_open_is_single_probe():
    now = [0.0]
    allow_response = [False]

    def handler(request):
        if allow_response[0]:
            return httpx.Response(200, json=ORDER)
        return httpx.Response(503)

    instance, client, breaker = reader(handler, attempts=1, threshold=2, clock=lambda: now[0])
    with client:
        for _ in range(2):
            with pytest.raises(ConnectorUnavailable):
                instance.get("https://erp.test/orders/SO-1001", ERPOrder, "order_id", "SO-1001")
        with pytest.raises(ConnectorCircuitOpen):
            instance.get("https://erp.test/orders/SO-1001", ERPOrder, "order_id", "SO-1001")
        now[0] = 31
        permit = breaker.acquire()
        with ThreadPoolExecutor(max_workers=2) as executor:
            failures = list(executor.map(lambda _: _acquire_error(breaker), range(2)))
        assert failures == [ConnectorCircuitOpen, ConnectorCircuitOpen]
        breaker.failure(permit)
        assert breaker.state == "open"
        now[0] = 62
        allow_response[0] = True
        assert instance.get("https://erp.test/orders/SO-1001", ERPOrder, "order_id", "SO-1001").order_id == "SO-1001"
        assert breaker.state == "closed"


def _acquire_error(breaker):
    try:
        breaker.acquire()
    except Exception as exc:
        return type(exc)
    return None


def test_breakers_are_isolated_per_upstream():
    settings = ConnectorSettings(
        mode="http", erp_base_url="https://erp.test", logistics_base_url="https://log.test",
        attempts=1, breaker_threshold=1,
    )

    def handler(request):
        if request.url.host == "erp.test":
            return httpx.Response(503)
        return httpx.Response(200, json={
            "shipment_id": "SHP-1", "carrier": "C", "status": "moving",
            "current_eta": "2026-10-01", "last_event": "Departed",
        })

    bundle = create_connector_bundle(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ConnectorUnavailable):
        bundle.tools.get_erp_order("SO-1")
    assert bundle.tools.get_logistics_status("SHP-1").status == "moving"
    bundle.close()


def test_http_configuration_requires_https_except_loopback(monkeypatch):
    monkeypatch.setenv("CONNECTOR_MODE", "http")
    monkeypatch.setenv("LOGISTICS_BASE_URL", "https://log.example")
    for url in ("http://erp.example", "ftp://erp.example", "https://user:secret@erp.example"):
        monkeypatch.setenv("ERP_BASE_URL", url)
        with pytest.raises(ConfigurationError):
            ConnectorSettings.from_env()
    monkeypatch.setenv("ERP_BASE_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("LOGISTICS_BASE_URL", "http://localhost:9001")
    assert ConnectorSettings.from_env().mode == "http"
