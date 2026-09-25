from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from time import perf_counter
from typing import TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.connectors.base import EventSink
from app.connectors.models import ERPOrder, ShipmentNote, ShipmentStatus
from app.connectors.resilience import Backoff, CircuitBreaker
from app.errors import ConnectorBadResponse, ConnectorTimeout, ConnectorUnavailable, MissingEvidence

T = TypeVar("T", bound=BaseModel)
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


def _emit(sink: EventSink | None, event: str, **details) -> None:
    if sink:
        sink(event, details)


def retry_after_seconds(value: str | None, now=lambda: datetime.now(timezone.utc)) -> float | None:
    if not value:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            delay = (target - now()).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    if not isfinite(delay):
        return None
    if delay < 0:
        return 0.0
    return min(delay, 5.0)


class ResilientHttpReader:
    def __init__(self, client: httpx.Client, upstream: str, breaker: CircuitBreaker, attempts: int = 3, backoff: Backoff | None = None):
        self.client = client
        self.upstream = upstream
        self.breaker = breaker
        self.attempts = attempts
        self.backoff = backoff or Backoff()

    def get(self, url: str, model: type[T], expected_field: str, expected_id: str, emit: EventSink | None = None) -> T:
        permit = self.breaker.acquire(emit)
        terminal_error = None
        for attempt in range(1, self.attempts + 1):
            started = perf_counter()
            _emit(emit, "connector_attempt_started", upstream=self.upstream, attempt=attempt)
            try:
                response = self.client.get(url)
            except httpx.TimeoutException:
                terminal_error = ConnectorTimeout()
                status = None
            except httpx.TransportError:
                terminal_error = ConnectorUnavailable()
                status = None
            else:
                status = response.status_code
                if status == 404:
                    self.breaker.success(permit, emit)
                    _emit(emit, "connector_attempt_failed", upstream=self.upstream, attempt=attempt, upstream_status=404, error_code="missing_evidence", duration_ms=round((perf_counter() - started) * 1000, 3))
                    raise MissingEvidence()
                if 200 <= status < 300:
                    try:
                        record = model.model_validate(response.json())
                    except (ValueError, ValidationError):
                        self.breaker.failure(permit, emit)
                        _emit(emit, "connector_attempt_failed", upstream=self.upstream, attempt=attempt, upstream_status=status, error_code="connector_bad_response", duration_ms=round((perf_counter() - started) * 1000, 3))
                        raise ConnectorBadResponse() from None
                    if getattr(record, expected_field) != expected_id:
                        self.breaker.failure(permit, emit)
                        _emit(emit, "connector_attempt_failed", upstream=self.upstream, attempt=attempt, upstream_status=status, error_code="connector_bad_response", duration_ms=round((perf_counter() - started) * 1000, 3))
                        raise ConnectorBadResponse()
                    self.breaker.success(permit, emit)
                    _emit(emit, "connector_attempt_completed", upstream=self.upstream, attempt=attempt, attempt_count=attempt, upstream_status=status, duration_ms=round((perf_counter() - started) * 1000, 3))
                    return record
                terminal_error = ConnectorUnavailable()
                if status not in RETRYABLE_STATUSES:
                    self.breaker.failure(permit, emit)
                    _emit(emit, "connector_attempt_failed", upstream=self.upstream, attempt=attempt, upstream_status=status, error_code=terminal_error.code, duration_ms=round((perf_counter() - started) * 1000, 3))
                    raise terminal_error

            _emit(emit, "connector_attempt_failed", upstream=self.upstream, attempt=attempt, upstream_status=status, error_code=terminal_error.code, duration_ms=round((perf_counter() - started) * 1000, 3))
            if attempt < self.attempts:
                server_delay = retry_after_seconds(response.headers.get("Retry-After")) if status in RETRYABLE_STATUSES else None
                delay = server_delay if server_delay is not None else self.backoff.full_jitter(attempt)
                _emit(emit, "connector_retry_scheduled", upstream=self.upstream, attempt=attempt, next_attempt=attempt + 1, delay_ms=round(delay * 1000, 3), upstream_status=status)
                self.backoff.sleep(delay)
        self.breaker.failure(permit, emit)
        terminal_error.metadata = {"attempt_count": self.attempts, "upstream_status": status}
        raise terminal_error


class HttpERPConnector:
    def __init__(self, base_url: str, reader: ResilientHttpReader):
        self.base_url = base_url
        self.reader = reader

    def get_order(self, order_id: str, emit: EventSink | None = None) -> ERPOrder:
        return self.reader.get(f"{self.base_url}/orders/{quote(order_id, safe='')}", ERPOrder, "order_id", order_id, emit)


class HttpLogisticsConnector:
    def __init__(self, base_url: str, reader: ResilientHttpReader):
        self.base_url = base_url
        self.reader = reader

    def get_shipment_status(self, shipment_id: str, emit: EventSink | None = None) -> ShipmentStatus:
        return self.reader.get(f"{self.base_url}/shipments/{quote(shipment_id, safe='')}", ShipmentStatus, "shipment_id", shipment_id, emit)

    def get_shipment_note(self, shipment_id: str, emit: EventSink | None = None) -> ShipmentNote:
        return self.reader.get(f"{self.base_url}/shipments/{quote(shipment_id, safe='')}/note", ShipmentNote, "shipment_id", shipment_id, emit)
