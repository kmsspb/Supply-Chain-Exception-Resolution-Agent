"""Development-only process-local tracing, isolated by analysis run."""

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from uuid import uuid4

_AUDIT_LOG: list[dict] = []
_LOCK = Lock()


class RunTrace:
    def __init__(self, exception_id: str, provider: str):
        self.run_id = str(uuid4())
        self.exception_id = exception_id
        self.provider = provider
        self.started = perf_counter()
        self.sequence = 0

    @property
    def elapsed_ms(self) -> float:
        return round((perf_counter() - self.started) * 1000, 3)

    def log(self, event_type: str, **details) -> dict:
        with _LOCK:
            self.sequence += 1
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "exception_id": self.exception_id,
                "run_id": self.run_id,
                "sequence": self.sequence,
                "details": {"provider": self.provider, **deepcopy(details)},
            }
            _AUDIT_LOG.append(event)
            return deepcopy(event)


def get_events(exception_id: str | None = None, run_id: str | None = None) -> list[dict]:
    with _LOCK:
        return deepcopy([
            event for event in _AUDIT_LOG
            if (exception_id is None or event["exception_id"] == exception_id)
            and (run_id is None or event["run_id"] == run_id)
        ])


def clear_events() -> None:
    """Clear the development store, primarily for isolated tests."""
    with _LOCK:
        _AUDIT_LOG.clear()
