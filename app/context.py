"""Application-owned evidence; model output selects references, not facts."""

import json
from copy import deepcopy

from app.errors import CorruptData
from app.models import EvidenceItem, ReasoningContext


def build_context(exception: dict, order: dict, shipment: dict, note: dict) -> ReasoningContext:
    records = (exception, order, shipment, note)
    required = (
        ("exception_id", "order_id", "shipment_id"),
        ("order_id", "requested_delivery_date"),
        ("shipment_id", "current_eta", "status"),
        ("note_id", "shipment_id", "text"),
    )
    for record, keys in zip(records, required):
        if not isinstance(record, dict) or any(
            not isinstance(record.get(key), str) or not record[key].strip() for key in keys
        ):
            raise CorruptData()
    if (exception["order_id"] != order["order_id"]
        or exception["shipment_id"] != shipment["shipment_id"]
        or shipment["shipment_id"] != note["shipment_id"]):
        raise CorruptData()
    try:
        evidence = tuple(
            EvidenceItem(
                evidence_id=f"{prefix}:{record[key]}", source=source,
                raw_reference=record[key],
                fact=json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False),
            )
            for prefix, source, record, key in (
                ("erp", "ERP", order, "order_id"),
                ("logistics", "Logistics", shipment, "shipment_id"),
                ("note", "Carrier note", note, "note_id"),
            )
        )
    except (TypeError, ValueError):
        raise CorruptData() from None
    return ReasoningContext(
        exception=deepcopy(exception), order=deepcopy(order), shipment=deepcopy(shipment),
        note=deepcopy(note), evidence=evidence,
    )
