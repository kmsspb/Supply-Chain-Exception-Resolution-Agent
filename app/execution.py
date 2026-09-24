"""Shared execution for comparisons and evaluations; never scores recommendations."""

from app.audit import get_events
from app.config import Settings
from app.errors import ResolutionError
from app.reasoner import Reasoner, create_reasoner
from app.service import analyse_context


class UnavailableReasoner:
    def __init__(self, provider: str, error: ResolutionError):
        self.provider = provider
        self.error_type = type(error)

    def describe(self):
        return {}

    def resolve(self, context):
        raise self.error_type()


def configured_reasoners(provider: str) -> dict[str, Reasoner]:
    names = ("rule_based", "azure_openai") if provider == "both" else (provider,)
    reasoners = {}
    try:
        for name in names:
            try:
                reasoners[name] = create_reasoner(Settings.from_env(provider=name))
            except ResolutionError as exc:
                reasoners[name] = UnavailableReasoner(name, exc)
        return reasoners
    except Exception:
        close_reasoners(reasoners)
        raise


def close_reasoners(reasoners: dict[str, Reasoner]) -> None:
    for reasoner in reasoners.values():
        client = getattr(reasoner, "client", None)
        if client is not None:
            client.close()


def execute_context(context, reasoner: Reasoner) -> dict:
    try:
        recommendation = analyse_context(context, reasoner)
        run_id = recommendation.run_id
        outcome = {"status": "success", "recommendation": recommendation.model_dump(mode="json")}
    except ResolutionError as exc:
        run_id = exc.run_id
        outcome = {"status": "error", "error": {"code": exc.code, "message": exc.message}}
    events = get_events(context.exception["exception_id"], run_id)
    model_event = next((
        event for event in reversed(events)
        if event["event_type"] in {"model_completed", "model_failed"}
    ), None)
    outcome.update({
        "run_id": run_id,
        "metadata": model_event["details"].get("metadata", {}) if model_event else {},
        "elapsed_ms": events[-1]["details"].get("elapsed_ms") if events else None,
        "provider_elapsed_ms": model_event["details"].get("elapsed_ms") if model_event else None,
        "trace": events,
    })
    return outcome
