from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WarehouseUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class WarehouseOut(BaseModel):
    id: UUID
    name: str
    is_deleted: bool
    deleted_at: datetime | None

    model_config = {"from_attributes": True}


class ProductOut(BaseModel):
    id: UUID
    sku: str
    name: str

    model_config = {"from_attributes": True}


class StockCell(BaseModel):
    warehouse_id: UUID
    warehouse_name: str
    warehouse_deleted: bool
    on_hand: int
    reserved_fbs: int
    available: int


class StockRow(BaseModel):
    product_id: UUID
    sku: str
    name: str
    cells: list[StockCell]
    total_on_hand: int
    total_reserved_fbs: int
    total_available: int


class InTransitItem(BaseModel):
    kind: str
    id: UUID
    product_id: UUID
    sku: str
    product_name: str
    quantity: int
    from_warehouse: str | None
    to_label: str
    status: str
    created_at: datetime


class StockOverview(BaseModel):
    products: list[StockRow]
    warehouses: list[WarehouseOut]
    in_transit_transfers: list[InTransitItem]
    in_transit_fbo: list[InTransitItem]
    in_transit_fbs: list[InTransitItem]


class IdempotentRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)


class ReceiptRequest(IdempotentRequest):
    product_id: UUID
    warehouse_id: UUID
    quantity: int = Field(gt=0)


class TransferShipRequest(IdempotentRequest):
    product_id: UUID
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    quantity: int = Field(gt=0)


class TransferReceiveRequest(IdempotentRequest):
    shipment_id: UUID


class FbsReserveRequest(IdempotentRequest):
    product_id: UUID
    warehouse_id: UUID
    quantity: int = Field(gt=0)


class FbsActionRequest(IdempotentRequest):
    order_id: UUID


class FboShipRequest(IdempotentRequest):
    product_id: UUID
    warehouse_id: UUID
    quantity: int = Field(gt=0)


class FboReceiveRequest(IdempotentRequest):
    shipment_id: UUID


class OperationOut(BaseModel):
    id: UUID
    idempotency_key: str
    type: str
    product_sku: str | None
    product_name: str | None
    quantity: int
    from_warehouse: str | None
    to_warehouse: str | None
    related_entity_id: UUID | None
    note: str | None
    created_at: datetime


class ShortageInfo(BaseModel):
    code: str = "insufficient_on_selected_warehouse"
    message: str
    requested: int
    available_on_selected: int
    total_available: int
    alternatives: list[dict]


class ActionResult(BaseModel):
    replayed: bool = False
    operation_id: UUID | None = None
    entity_id: UUID | None = None
    detail: str | None = None
