from pydantic import ValidationError

from app import repository
from app.connectors.base import EventSink
from app.connectors.models import ERPOrder, ShipmentNote, ShipmentStatus
from app.errors import CorruptData, MissingEvidence


def _validated(model, record):
    if record is None:
        raise MissingEvidence()
    try:
        return model.model_validate(record)
    except ValidationError:
        raise CorruptData() from None


class FixtureERPConnector:
    def get_order(self, order_id: str, emit: EventSink | None = None) -> ERPOrder:
        return _validated(ERPOrder, repository.get_order(order_id))


class FixtureLogisticsConnector:
    def get_shipment_status(self, shipment_id: str, emit: EventSink | None = None) -> ShipmentStatus:
        return _validated(ShipmentStatus, repository.get_shipment(shipment_id))

    def get_shipment_note(self, shipment_id: str, emit: EventSink | None = None) -> ShipmentNote:
        return _validated(ShipmentNote, repository.get_note(shipment_id))
