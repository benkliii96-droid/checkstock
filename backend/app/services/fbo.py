from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import FboShipment, Operation, OperationType, ShipmentStatus
from app.services.errors import AppError
from app.services.stock import (
    assert_available,
    find_operation,
    require_active_warehouse,
    require_product,
)


def ship(
    db: Session,
    *,
    idempotency_key: str,
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    quantity: int,
) -> dict:
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.related_entity_id,
            "detail": "Повторное подтверждение: отправка FBO уже учтена",
        }

    product = require_product(db, product_id)
    warehouse = require_active_warehouse(db, warehouse_id)
    bal = assert_available(db, warehouse, product, quantity)
    bal.on_hand -= quantity

    shipment = FboShipment(
        product_id=product.id,
        from_warehouse_id=warehouse.id,
        quantity=quantity,
        status=ShipmentStatus.IN_TRANSIT,
    )
    db.add(shipment)
    db.flush()

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBO_SHIP,
        product_id=product.id,
        quantity=quantity,
        from_warehouse_id=warehouse.id,
        related_entity_id=shipment.id,
        note=f"Отправка FBO {quantity} шт. со склада «{warehouse.name}» на маркетплейс",
    )
    db.add(op)
    db.flush()
    shipment.ship_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": shipment.id, "detail": op.note}


def receive(db: Session, *, idempotency_key: str, shipment_id: uuid.UUID) -> dict:
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.related_entity_id,
            "detail": "Повторное подтверждение: приёмка FBO уже учтена",
        }

    shipment = db.scalar(
        select(FboShipment)
        .options(joinedload(FboShipment.product), joinedload(FboShipment.from_warehouse))
        .where(FboShipment.id == shipment_id)
    )
    if shipment is None:
        raise AppError("Отправка FBO не найдена", code="fbo_not_found", status_code=404)
    if shipment.status != ShipmentStatus.IN_TRANSIT:
        raise AppError("Отправка FBO уже принята", code="fbo_not_in_transit")

    shipment.status = ShipmentStatus.RECEIVED
    shipment.received_at = datetime.now(timezone.utc)

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBO_RECEIVE,
        product_id=shipment.product_id,
        quantity=shipment.quantity,
        from_warehouse_id=shipment.from_warehouse_id,
        related_entity_id=shipment.id,
        note=(
            f"Приёмка FBO на складе маркетплейса: {shipment.quantity} шт. "
            f"({shipment.product.sku})"
        ),
    )
    db.add(op)
    db.flush()
    shipment.receive_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": shipment.id, "detail": op.note}


def list_open(db: Session) -> list[FboShipment]:
    return list(
        db.scalars(
            select(FboShipment)
            .options(joinedload(FboShipment.product), joinedload(FboShipment.from_warehouse))
            .where(FboShipment.status == ShipmentStatus.IN_TRANSIT)
            .order_by(FboShipment.created_at.desc())
        ).all()
    )
