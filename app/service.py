from app import repository, tools
from app.audit import log_event
from app.reasoner import RuleBasedReasoner

reasoner = RuleBasedReasoner()


def resolve_exception(exception_id: str):
    exception = repository.get_exception(exception_id)
    if not exception:
        raise ValueError(f"Exception {exception_id} not found")

    log_event("resolution_started", exception_id, {"order_id": exception["order_id"]})

    order = tools.get_erp_order(exception["order_id"])
    shipment = tools.get_logistics_status(exception["shipment_id"])
    note = tools.get_shipment_note(exception["shipment_id"])

    log_event(
        "evidence_collected",
        exception_id,
        {
            "erp_order": order["order_id"],
            "shipment": shipment["shipment_id"],
            "note": note["note_id"],
        },
    )

    recommendation = reasoner.resolve(exception, order, shipment, note)

    log_event(
        "recommendation_created",
        exception_id,
        {
            "category": recommendation.category,
            "confidence": recommendation.confidence,
            "risk_level": recommendation.risk_level,
            "human_approval_required": recommendation.human_approval_required,
        },
    )

    return recommendation
