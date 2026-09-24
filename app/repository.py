import json
from pathlib import Path

from app.errors import CorruptData

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str) -> list[dict]:
    try:
        with open(DATA_DIR / name, "r", encoding="utf-8") as source:
            records = json.load(source)
        if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
            raise CorruptData()
        return records
    except (OSError, UnicodeError, ValueError):
        raise CorruptData() from None


def _find(name: str, key: str, value: str):
    records = _load(name)
    if any(not isinstance(record.get(key), str) or not record[key].strip() for record in records):
        raise CorruptData()
    matches = [record for record in records if record[key] == value]
    if len(matches) > 1:
        raise CorruptData()
    return matches[0] if matches else None


def get_exception(exception_id: str):
    return _find("exceptions.json", "exception_id", exception_id)


def get_order(order_id: str):
    return _find("erp_orders.json", "order_id", order_id)


def get_shipment(shipment_id: str):
    return _find("shipments.json", "shipment_id", shipment_id)


def get_note(shipment_id: str):
    return _find("notes.json", "shipment_id", shipment_id)
