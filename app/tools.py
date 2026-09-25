from app.connectors.fixture import FixtureERPConnector, FixtureLogisticsConnector
from app.connectors.service import EnterpriseToolService

_FIXTURES = EnterpriseToolService(FixtureERPConnector(), FixtureLogisticsConnector())


def get_erp_order(order_id: str) -> dict:
    """Read-only ERP tool."""
    return _FIXTURES.get_erp_order(order_id).model_dump(mode="json")


def get_logistics_status(shipment_id: str) -> dict:
    """Read-only logistics/carrier tool."""
    return _FIXTURES.get_logistics_status(shipment_id).model_dump(mode="json")


def get_shipment_note(shipment_id: str) -> dict:
    """Read-only unstructured communication tool."""
    return _FIXTURES.get_shipment_note(shipment_id).model_dump(mode="json")
