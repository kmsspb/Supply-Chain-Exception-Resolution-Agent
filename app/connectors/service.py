from app.audit import RunTrace
from app.connectors.base import ERPConnector, LogisticsConnector
from app.connectors.models import ERPOrder, ShipmentNote, ShipmentStatus


class EnterpriseToolService:
    def __init__(self, erp: ERPConnector, logistics: LogisticsConnector):
        self.erp = erp
        self.logistics = logistics

    @staticmethod
    def _sink(trace: RunTrace | None):
        if trace is None:
            return None
        return lambda event, details: trace.log(event, **details)

    def get_erp_order(self, order_id: str, trace: RunTrace | None = None) -> ERPOrder:
        return self.erp.get_order(order_id, self._sink(trace))

    def get_logistics_status(self, shipment_id: str, trace: RunTrace | None = None) -> ShipmentStatus:
        return self.logistics.get_shipment_status(shipment_id, self._sink(trace))

    def get_shipment_note(self, shipment_id: str, trace: RunTrace | None = None) -> ShipmentNote:
        return self.logistics.get_shipment_note(shipment_id, self._sink(trace))
