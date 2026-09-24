from datetime import datetime, timezone

_AUDIT_LOG: list[dict] = []


def log_event(event_type: str, exception_id: str, details: dict):
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "exception_id": exception_id,
        "details": details,
    }
    _AUDIT_LOG.append(event)
    return event


def get_events(exception_id: str | None = None):
    if exception_id is None:
        return _AUDIT_LOG
    return [x for x in _AUDIT_LOG if x["exception_id"] == exception_id]
