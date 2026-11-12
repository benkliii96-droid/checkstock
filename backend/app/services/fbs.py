from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import FbsOrder, FbsStatus, Operation, OperationType
from app.services.errors import AppError
from app.services.stock import (
    assert_available,
    find_operation,
    get_or_create_balance,
    require_active_warehouse,
    require_product,
)


def reserve(
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
            "detail": "Повторное подтверждение: резерв FBS уже создан",
        }

    product = require_product(db, product_id)
    warehouse = require_active_warehouse(db, warehouse_id)
    bal = assert_available(db, warehouse, product, quantity)
    bal.reserved_fbs += quantity

    order = FbsOrder(
        product_id=product.id,
        warehouse_id=warehouse.id,
        quantity=quantity,
        status=FbsStatus.RESERVED,
    )
    db.add(order)
    db.flush()

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBS_RESERVE,
        product_id=product.id,
        quantity=quantity,
        from_warehouse_id=warehouse.id,
        related_entity_id=order.id,
        note=f"Резерв FBS {quantity} шт. на «{warehouse.name}»",
    )
    db.add(op)
    db.flush()
    order.reserve_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": order.id, "detail": op.note}


def cancel(db: Session, *, idempotency_key: str, order_id: uuid.UUID) -> dict:
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.related_entity_id,
            "detail": "Повторное подтверждение: отмена FBS уже учтена",
        }

    order = db.scalar(
        select(FbsOrder)
        .options(joinedload(FbsOrder.product), joinedload(FbsOrder.warehouse))
        .where(FbsOrder.id == order_id)
    )
    if order is None:
        raise AppError("Заказ FBS не найден", code="fbs_not_found", status_code=404)
    if order.status != FbsStatus.RESERVED:
        raise AppError("Отменить можно только зарезервированный заказ", code="fbs_bad_status")

    bal = get_or_create_balance(db, order.warehouse_id, order.product_id)
    if bal.reserved_fbs < order.quantity:
        raise AppError("Внутренняя ошибка: резерв меньше заказа", code="reserve_corrupt", status_code=500)
    bal.reserved_fbs -= order.quantity
    order.status = FbsStatus.CANCELLED

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBS_CANCEL,
        product_id=order.product_id,
        quantity=order.quantity,
        from_warehouse_id=order.warehouse_id,
        related_entity_id=order.id,
        note=f"Отмена резерва FBS {order.quantity} шт. на «{order.warehouse.name}»",
    )
    db.add(op)
    db.flush()
    order.cancel_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": order.id, "detail": op.note}


def ship(db: Session, *, idempotency_key: str, order_id: uuid.UUID) -> dict:
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.related_entity_id,
            "detail": "Повторное подтверждение: отправка FBS уже учтена",
        }

    order = db.scalar(
        select(FbsOrder)
        .options(joinedload(FbsOrder.product), joinedload(FbsOrder.warehouse))
        .where(FbsOrder.id == order_id)
    )
    if order is None:
        raise AppError("Заказ FBS не найден", code="fbs_not_found", status_code=404)
    if order.status != FbsStatus.RESERVED:
        raise AppError("Отправить можно только зарезервированный заказ", code="fbs_bad_status")

    require_active_warehouse(db, order.warehouse_id)
    bal = get_or_create_balance(db, order.warehouse_id, order.product_id)
    if bal.reserved_fbs < order.quantity or bal.on_hand < order.quantity:
        raise AppError("Внутренняя ошибка: недостаточно остатка для отправки FBS", code="fbs_corrupt", status_code=500)

    bal.reserved_fbs -= order.quantity
    bal.on_hand -= order.quantity
    order.status = FbsStatus.SHIPPED

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.FBS_SHIP,
        product_id=order.product_id,
        quantity=order.quantity,
        from_warehouse_id=order.warehouse_id,
        related_entity_id=order.id,
        note=f"Отправка FBS к клиенту {order.quantity} шт. со склада «{order.warehouse.name}»",
    )
    db.add(op)
    db.flush()
    order.ship_operation_id = op.id
    db.commit()
    db.refresh(op)
    return {"replayed": False, "operation_id": op.id, "entity_id": order.id, "detail": op.note}


def list_orders(db: Session, status: FbsStatus | None = None) -> list[FbsOrder]:
    stmt = (
        select(FbsOrder)
        .options(joinedload(FbsOrder.product), joinedload(FbsOrder.warehouse))
        .order_by(FbsOrder.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(FbsOrder.status == status)
    return list(db.scalars(stmt).all())
