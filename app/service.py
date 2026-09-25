from collections.abc import Callable
from time import perf_counter

from app import repository, tools
from app.audit import RunTrace
from app.context import build_context
from app.connectors.service import EnterpriseToolService
from app.errors import CorruptData, ExceptionNotFound, ResolutionError
from app.models import ReasoningContext, ResolutionRecommendation
from app.reasoner import Reasoner, create_reasoner
from app.validation import validate_recommendation


def _connector(trace: RunTrace, name: str, function: Callable, record_id: str) -> dict:
    started = perf_counter()
    trace.log("connector_started", tool=name, record_id=record_id)
    try:
        record = function(record_id)
    except ResolutionError as exc:
        trace.log(
            "connector_failed", tool=name, error_code=exc.code,
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
            **exc.metadata,
        )
        raise
    except Exception:
        trace.log(
            "connector_failed", tool=name, error_code="corrupt_local_data",
            elapsed_ms=round((perf_counter() - started) * 1000, 3),
        )
        raise CorruptData() from None
    trace.log(
        "connector_completed", tool=name, record_id=record_id,
        elapsed_ms=round((perf_counter() - started) * 1000, 3),
    )
    return record


def collect_context(
    exception_id: str, trace: RunTrace, tool_service: EnterpriseToolService | None = None,
) -> ReasoningContext:
    exception = repository.get_exception(exception_id)
    if exception is None:
        raise ExceptionNotFound()
    if any(
        not isinstance(exception.get(key), str) or not exception[key].strip()
        for key in ("order_id", "shipment_id")
    ):
        raise CorruptData()
    if tool_service is None:
        order_fn, shipment_fn, note_fn = tools.get_erp_order, tools.get_logistics_status, tools.get_shipment_note
    else:
        order_fn = lambda record_id: tool_service.get_erp_order(record_id, trace).model_dump(mode="json")
        shipment_fn = lambda record_id: tool_service.get_logistics_status(record_id, trace).model_dump(mode="json")
        note_fn = lambda record_id: tool_service.get_shipment_note(record_id, trace).model_dump(mode="json")
    order = _connector(trace, "get_erp_order", order_fn, exception["order_id"])
    shipment = _connector(trace, "get_logistics_status", shipment_fn, exception["shipment_id"])
    note = _connector(trace, "get_shipment_note", note_fn, exception["shipment_id"])
    return build_context(exception, order, shipment, note)


def _execute(
    exception_id: str, reasoner: Reasoner, loader: Callable[[RunTrace], ReasoningContext],
) -> ResolutionRecommendation:
    trace = RunTrace(exception_id, reasoner.provider)
    trace.log("resolution_started")
    try:
        context = loader(trace)
        trace.log("evidence_collected", context=context.model_dump(mode="json"))
        trace.log("model_invoked", **reasoner.describe())
        model_started = perf_counter()
        try:
            result = reasoner.resolve(context)
        except ResolutionError as exc:
            trace.log(
                "model_failed", error_code=exc.code, metadata=exc.metadata,
                elapsed_ms=round((perf_counter() - model_started) * 1000, 3),
            )
            if exc.status_code == 502:
                trace.log("output_validation_failed", error_code=exc.code)
            raise
        trace.log(
            "model_completed", metadata=result.metadata,
            elapsed_ms=round((perf_counter() - model_started) * 1000, 3),
        )
        try:
            recommendation = validate_recommendation(
                result.recommendation, context, trace.run_id, reasoner.provider,
            )
        except ResolutionError as exc:
            trace.log("output_validation_failed", error_code=exc.code)
            raise
        trace.log("output_validated")
        trace.log("recommendation_created", recommendation=recommendation.model_dump(mode="json"))
        trace.log("resolution_completed", elapsed_ms=trace.elapsed_ms)
        return recommendation
    except ResolutionError as exc:
        error = exc
    except Exception:
        # Trace and return a safe error even for an unexpected adapter/programming failure.
        error = ResolutionError()
    error.run_id = trace.run_id
    trace.log("resolution_failed", error_code=error.code, elapsed_ms=trace.elapsed_ms)
    raise error from None


def resolve_exception(
    exception_id: str, reasoner: Reasoner | None = None,
    tool_service: EnterpriseToolService | None = None,
) -> ResolutionRecommendation:
    selected = reasoner if reasoner is not None else create_reasoner()
    return _execute(exception_id, selected, lambda trace: collect_context(exception_id, trace, tool_service))


def analyse_context(context: ReasoningContext, reasoner: Reasoner) -> ResolutionRecommendation:
    """Analyse an already collected snapshot, used for fair provider comparisons."""
    return _execute(context.exception["exception_id"], reasoner, lambda trace: context)
