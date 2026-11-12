from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import raise_app_error
from app.database import get_db
from app.schemas import (
    ActionResult,
    FboReceiveRequest,
    FboShipRequest,
    FbsActionRequest,
    FbsReserveRequest,
    OperationOut,
    ProductOut,
    ReceiptRequest,
    StockOverview,
    TransferReceiveRequest,
    TransferShipRequest,
    WarehouseCreate,
    WarehouseOut,
    WarehouseUpdate,
)
from app.services import fbo, fbs, history, movements, stock, warehouses
from app.services.errors import AppError
from app.models import FbsStatus, Product
from sqlalchemy import select

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/stock", response_model=StockOverview)
def get_stock(db: Session = Depends(get_db)):
    return stock.overview(db)


@router.get("/products", response_model=list[ProductOut])
def get_products(db: Session = Depends(get_db)):
    return list(db.scalars(select(Product).order_by(Product.sku)).all())


@router.get("/warehouses", response_model=list[WarehouseOut])
def get_warehouses(include_deleted: bool = True, db: Session = Depends(get_db)):
    return warehouses.list_warehouses(db, include_deleted=include_deleted)


@router.post("/warehouses", response_model=WarehouseOut)
def create_warehouse(body: WarehouseCreate, db: Session = Depends(get_db)):
    try:
        return warehouses.create_warehouse(db, body.name)
    except AppError as exc:
        raise_app_error(exc)


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseOut)
def rename_warehouse(warehouse_id: UUID, body: WarehouseUpdate, db: Session = Depends(get_db)):
    try:
        return warehouses.rename_warehouse(db, warehouse_id, body.name)
    except AppError as exc:
        raise_app_error(exc)


@router.delete("/warehouses/{warehouse_id}", response_model=ActionResult)
def delete_warehouse(
    warehouse_id: UUID,
    idempotency_key: str = Query(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    try:
        return warehouses.soft_delete_warehouse(db, warehouse_id, idempotency_key)
    except AppError as exc:
        raise_app_error(exc)


@router.post("/movements/receipt", response_model=ActionResult)
def post_receipt(body: ReceiptRequest, db: Session = Depends(get_db)):
    try:
        return movements.receipt(
            db,
            idempotency_key=body.idempotency_key,
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
        )
    except AppError as exc:
        raise_app_error(exc)


@router.post("/movements/transfer/ship", response_model=ActionResult)
def post_transfer_ship(body: TransferShipRequest, db: Session = Depends(get_db)):
    try:
        return movements.transfer_ship(
            db,
            idempotency_key=body.idempotency_key,
            product_id=body.product_id,
            from_warehouse_id=body.from_warehouse_id,
            to_warehouse_id=body.to_warehouse_id,
            quantity=body.quantity,
        )
    except AppError as exc:
        raise_app_error(exc)


@router.post("/movements/transfer/receive", response_model=ActionResult)
def post_transfer_receive(body: TransferReceiveRequest, db: Session = Depends(get_db)):
    try:
        return movements.transfer_receive(
            db,
            idempotency_key=body.idempotency_key,
            shipment_id=body.shipment_id,
        )
    except AppError as exc:
        raise_app_error(exc)


@router.post("/fbs/reserve", response_model=ActionResult)
def post_fbs_reserve(body: FbsReserveRequest, db: Session = Depends(get_db)):
    try:
        return fbs.reserve(
            db,
            idempotency_key=body.idempotency_key,
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
        )
    except AppError as exc:
        raise_app_error(exc)


@router.post("/fbs/cancel", response_model=ActionResult)
def post_fbs_cancel(body: FbsActionRequest, db: Session = Depends(get_db)):
    try:
        return fbs.cancel(db, idempotency_key=body.idempotency_key, order_id=body.order_id)
    except AppError as exc:
        raise_app_error(exc)


@router.post("/fbs/ship", response_model=ActionResult)
def post_fbs_ship(body: FbsActionRequest, db: Session = Depends(get_db)):
    try:
        return fbs.ship(db, idempotency_key=body.idempotency_key, order_id=body.order_id)
    except AppError as exc:
        raise_app_error(exc)


@router.get("/fbs/orders")
def get_fbs_orders(status: str | None = None, db: Session = Depends(get_db)):
    st = FbsStatus(status) if status else None
    orders = fbs.list_orders(db, status=st)
    return [
        {
            "id": o.id,
            "product_id": o.product_id,
            "sku": o.product.sku,
            "product_name": o.product.name,
            "warehouse_id": o.warehouse_id,
            "warehouse_name": o.warehouse.name,
            "quantity": o.quantity,
            "status": o.status.value,
            "created_at": o.created_at,
        }
        for o in orders
    ]


@router.post("/fbo/ship", response_model=ActionResult)
def post_fbo_ship(body: FboShipRequest, db: Session = Depends(get_db)):
    try:
        return fbo.ship(
            db,
            idempotency_key=body.idempotency_key,
            product_id=body.product_id,
            warehouse_id=body.warehouse_id,
            quantity=body.quantity,
        )
    except AppError as exc:
        raise_app_error(exc)


@router.post("/fbo/receive", response_model=ActionResult)
def post_fbo_receive(body: FboReceiveRequest, db: Session = Depends(get_db)):
    try:
        return fbo.receive(db, idempotency_key=body.idempotency_key, shipment_id=body.shipment_id)
    except AppError as exc:
        raise_app_error(exc)


@router.get("/operations", response_model=list[OperationOut])
def get_operations(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    return history.list_operations(db, limit=limit)
