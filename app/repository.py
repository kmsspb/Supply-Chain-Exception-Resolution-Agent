import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load(name: str):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def get_exception(exception_id: str):
    return next((x for x in _load("exceptions.json") if x["exception_id"] == exception_id), None)


def get_order(order_id: str):
    return next((x for x in _load("erp_orders.json") if x["order_id"] == order_id), None)


def get_shipment(shipment_id: str):
    return next((x for x in _load("shipments.json") if x["shipment_id"] == shipment_id), None)


def get_note(shipment_id: str):
    return next((x for x in _load("notes.json") if x["shipment_id"] == shipment_id), None)
