from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Operation, OperationType, ShipmentStatus, TransferShipment
from app.services.errors import AppError
from app.services.stock import (
    assert_available,
    find_operation,
    get_or_create_balance,
    require_active_warehouse,
    require_product,
)


def receipt(
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
            "entity_id": None,
            "detail": "Повторное подтверждение: приход уже учтён",
        }

    product = require_product(db, product_id)
    warehouse = require_active_warehouse(db, warehouse_id)
    bal = get_or_create_balance(db, warehouse.id, product.id)
    bal.on_hand += quantity

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.RECEIPT,
        product_id=product.id,
        quantity=quantity,
        to_warehouse_id=warehouse.id,
        note=f"Приход {quantity} шт. на «{warehouse.name}»",
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": None, "detail": op.note}


def transfer_ship(
    db: Session,
    *,
    idempotency_key: str,
    product_id: uuid.UUID,
    from_warehouse_id: uuid.UUID,
    to_warehouse_id: uuid.UUID,
    quantity: int,
) -> dict:
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.related_entity_id,
            "detail": "Повторное подтверждение: отправка перемещения уже учтена",
        }

    if from_warehouse_id == to_warehouse_id:
        raise AppError("Нельзя перемещать на тот же склад", code="same_warehouse")

    product = require_product(db, product_id)
    src = require_active_warehouse(db, from_warehouse_id)
    dst = require_active_warehouse(db, to_warehouse_id)
    bal = assert_available(db, src, product, quantity)
    bal.on_hand -= quantity

    shipment = TransferShipment(
        product_id=product.id,
        from_warehouse_id=src.id,
        to_warehouse_id=dst.id,
        quantity=quantity,
        status=ShipmentStatus.IN_TRANSIT,
    )
    db.add(shipment)
    db.flush()

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.TRANSFER_SHIP,
        product_id=product.id,
        quantity=quantity,
        from_warehouse_id=src.id,
        to_warehouse_id=dst.id,
        related_entity_id=shipment.id,
        note=f"Отправка перемещения {quantity} шт. «{src.name}» → «{dst.name}»",
    )
    db.add(op)
    db.flush()
    shipment.ship_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": shipment.id, "detail": op.note}


def transfer_receive(db: Session, *, idempotency_key: str, shipment_id: uuid.UUID) -> dict:
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.related_entity_id,
            "detail": "Повторное подтверждение: приёмка перемещения уже учтена",
        }

    shipment = db.scalar(
        select(TransferShipment)
        .options(
            joinedload(TransferShipment.product),
            joinedload(TransferShipment.from_warehouse),
            joinedload(TransferShipment.to_warehouse),
        )
        .where(TransferShipment.id == shipment_id)
    )
    if shipment is None:
        raise AppError("Перемещение не найдено", code="transfer_not_found", status_code=404)
    if shipment.status != ShipmentStatus.IN_TRANSIT:
        raise AppError("Перемещение уже принято или отменено", code="transfer_not_in_transit")

    # Приёмка разрешена даже на soft-deleted ФФ — иначе товар зависает «в пути».
    dst = shipment.to_warehouse
    if dst is None:
        raise AppError("Склад назначения не найден", code="warehouse_not_found", status_code=404)

    bal = get_or_create_balance(db, dst.id, shipment.product_id)
    bal.on_hand += shipment.quantity
    shipment.status = ShipmentStatus.RECEIVED
    shipment.received_at = datetime.now(timezone.utc)

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.TRANSFER_RECEIVE,
        product_id=shipment.product_id,
        quantity=shipment.quantity,
        from_warehouse_id=shipment.from_warehouse_id,
        to_warehouse_id=shipment.to_warehouse_id,
        related_entity_id=shipment.id,
        note=(
            f"Приёмка перемещения {shipment.quantity} шт. "
            f"«{shipment.from_warehouse.name}» → «{dst.name}»"
        ),
    )
    db.add(op)
    db.flush()
    shipment.receive_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": shipment.id, "detail": op.note}


def list_open_transfers(db: Session) -> list[TransferShipment]:
    return list(
        db.scalars(
            select(TransferShipment)
            .options(
                joinedload(TransferShipment.product),
                joinedload(TransferShipment.from_warehouse),
                joinedload(TransferShipment.to_warehouse),
            )
            .where(TransferShipment.status == ShipmentStatus.IN_TRANSIT)
            .order_by(TransferShipment.created_at.desc())
        ).all()
    )
