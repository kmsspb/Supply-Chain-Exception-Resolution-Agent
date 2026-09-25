from collections.abc import Callable
from typing import Any, Protocol

from app.connectors.models import ERPOrder, ShipmentNote, ShipmentStatus

EventSink = Callable[[str, dict[str, Any]], None]


class ERPConnector(Protocol):
    def get_order(self, order_id: str, emit: EventSink | None = None) -> ERPOrder: ...


class LogisticsConnector(Protocol):
    def get_shipment_status(self, shipment_id: str, emit: EventSink | None = None) -> ShipmentStatus: ...

    def get_shipment_note(self, shipment_id: str, emit: EventSink | None = None) -> ShipmentNote: ...
