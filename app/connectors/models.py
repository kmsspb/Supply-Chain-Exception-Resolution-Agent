from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConnectorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("blank values are not valid")
        return value


class ERPOrder(ConnectorRecord):
    order_id: str
    customer: str
    material: str
    quantity: int = Field(gt=0)
    requested_delivery_date: str
    incoterm: str
    order_status: str


class ShipmentStatus(ConnectorRecord):
    shipment_id: str
    carrier: str
    status: str
    current_eta: str
    last_event: str


class ShipmentNote(ConnectorRecord):
    note_id: str
    shipment_id: str
    text: str
