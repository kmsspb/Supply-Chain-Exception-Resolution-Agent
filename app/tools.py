from app import repository


def get_erp_order(order_id: str) -> dict:
    """Read-only ERP tool."""
    record = repository.get_order(order_id)
    if not record:
        raise ValueError(f"Order {order_id} not found")
    return record


def get_logistics_status(shipment_id: str) -> dict:
    """Read-only logistics/carrier tool."""
    record = repository.get_shipment(shipment_id)
    if not record:
        raise ValueError(f"Shipment {shipment_id} not found")
    return record


def get_shipment_note(shipment_id: str) -> dict:
    """Read-only unstructured communication tool."""
    record = repository.get_note(shipment_id)
    if not record:
        raise ValueError(f"No note found for shipment {shipment_id}")
    return record
