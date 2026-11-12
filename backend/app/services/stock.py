from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    FboShipment,
    FbsOrder,
    FbsStatus,
    Operation,
    Product,
    ShipmentStatus,
    StockBalance,
    TransferShipment,
    Warehouse,
)
from app.schemas import InTransitItem, StockCell, StockOverview, StockRow, WarehouseOut
from app.services.errors import AppError, ShortageError


def get_or_create_balance(db: Session, warehouse_id: uuid.UUID, product_id: uuid.UUID) -> StockBalance:
    bal = db.scalar(
        select(StockBalance).where(
            StockBalance.warehouse_id == warehouse_id,
            StockBalance.product_id == product_id,
        )
    )
    if bal is None:
        bal = StockBalance(warehouse_id=warehouse_id, product_id=product_id, on_hand=0, reserved_fbs=0)
        db.add(bal)
        db.flush()
    return bal


def require_active_warehouse(db: Session, warehouse_id: uuid.UUID) -> Warehouse:
    wh = db.get(Warehouse, warehouse_id)
    if wh is None:
        raise AppError("Склад не найден", code="warehouse_not_found", status_code=404)
    if wh.is_deleted:
        raise AppError(
            f"Склад «{wh.name}» удалён — операции с ним запрещены",
            code="warehouse_deleted",
            status_code=400,
        )
    return wh


def require_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise AppError("Товар не найден", code="product_not_found", status_code=404)
    return product


def find_operation(db: Session, idempotency_key: str) -> Operation | None:
    return db.scalar(select(Operation).where(Operation.idempotency_key == idempotency_key))


def assert_available(db: Session, warehouse: Warehouse, product: Product, quantity: int) -> StockBalance:
    bal = get_or_create_balance(db, warehouse.id, product.id)
    if bal.available >= quantity:
        return bal

    all_balances = db.scalars(
        select(StockBalance)
        .options(joinedload(StockBalance.warehouse))
        .where(StockBalance.product_id == product.id)
    ).all()

    alternatives = []
    total_available = 0
    for item in all_balances:
        if item.warehouse.is_deleted:
            continue
        avail = item.available
        total_available += avail
        if avail > 0 and item.warehouse_id != warehouse.id:
            alternatives.append(
                {
                    "warehouse_id": str(item.warehouse_id),
                    "warehouse_name": item.warehouse.name,
                    "available": avail,
                }
            )

    raise ShortageError(
        requested=quantity,
        available_on_selected=bal.available,
        total_available=total_available,
        alternatives=alternatives,
        warehouse_name=warehouse.name,
    )


def overview(db: Session) -> StockOverview:
    warehouses = db.scalars(select(Warehouse).order_by(Warehouse.name)).all()
    products = db.scalars(select(Product).order_by(Product.sku)).all()
    balances = db.scalars(
        select(StockBalance).options(joinedload(StockBalance.warehouse), joinedload(StockBalance.product))
    ).all()

    bal_map: dict[tuple[uuid.UUID, uuid.UUID], StockBalance] = {
        (b.warehouse_id, b.product_id): b for b in balances
    }

    rows: list[StockRow] = []
    for product in products:
        cells: list[StockCell] = []
        total_on_hand = 0
        total_reserved = 0
        total_available = 0
        for wh in warehouses:
            bal = bal_map.get((wh.id, product.id))
            on_hand = bal.on_hand if bal else 0
            reserved = bal.reserved_fbs if bal else 0
            available = on_hand - reserved
            cells.append(
                StockCell(
                    warehouse_id=wh.id,
                    warehouse_name=wh.name,
                    warehouse_deleted=wh.is_deleted,
                    on_hand=on_hand,
                    reserved_fbs=reserved,
                    available=available,
                )
            )
            total_on_hand += on_hand
            total_reserved += reserved
            total_available += available
        rows.append(
            StockRow(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                cells=cells,
                total_on_hand=total_on_hand,
                total_reserved_fbs=total_reserved,
                total_available=total_available,
            )
        )

    transfers = db.scalars(
        select(TransferShipment)
        .options(
            joinedload(TransferShipment.product),
            joinedload(TransferShipment.from_warehouse),
            joinedload(TransferShipment.to_warehouse),
        )
        .where(TransferShipment.status == ShipmentStatus.IN_TRANSIT)
        .order_by(TransferShipment.created_at.desc())
    ).all()

    fbo_list = db.scalars(
        select(FboShipment)
        .options(joinedload(FboShipment.product), joinedload(FboShipment.from_warehouse))
        .where(FboShipment.status == ShipmentStatus.IN_TRANSIT)
        .order_by(FboShipment.created_at.desc())
    ).all()

    fbs_shipped = db.scalars(
        select(FbsOrder)
        .options(joinedload(FbsOrder.product), joinedload(FbsOrder.warehouse))
        .where(FbsOrder.status == FbsStatus.SHIPPED)
        .order_by(FbsOrder.updated_at.desc())
    ).all()

    return StockOverview(
        products=rows,
        warehouses=[WarehouseOut.model_validate(w) for w in warehouses],
        in_transit_transfers=[
            InTransitItem(
                kind="transfer",
                id=t.id,
                product_id=t.product_id,
                sku=t.product.sku,
                product_name=t.product.name,
                quantity=t.quantity,
                from_warehouse=t.from_warehouse.name,
                to_label=t.to_warehouse.name,
                status=t.status.value,
                created_at=t.created_at,
            )
            for t in transfers
        ],
        in_transit_fbo=[
            InTransitItem(
                kind="fbo",
                id=s.id,
                product_id=s.product_id,
                sku=s.product.sku,
                product_name=s.product.name,
                quantity=s.quantity,
                from_warehouse=s.from_warehouse.name,
                to_label="Склад маркетплейса (FBO)",
                status=s.status.value,
                created_at=s.created_at,
            )
            for s in fbo_list
        ],
        in_transit_fbs=[
            InTransitItem(
                kind="fbs",
                id=o.id,
                product_id=o.product_id,
                sku=o.product.sku,
                product_name=o.product.name,
                quantity=o.quantity,
                from_warehouse=o.warehouse.name,
                to_label="Клиент (FBS)",
                status=o.status.value,
                created_at=o.created_at,
            )
            for o in fbs_shipped
        ],
    )
