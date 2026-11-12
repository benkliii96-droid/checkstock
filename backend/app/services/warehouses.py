from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Operation, OperationType, Warehouse
from app.services.errors import AppError
from app.services.stock import find_operation


def list_warehouses(db: Session, include_deleted: bool = True) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(Warehouse.name)
    if not include_deleted:
        stmt = stmt.where(Warehouse.is_deleted.is_(False))
    return list(db.scalars(stmt).all())


def create_warehouse(db: Session, name: str) -> Warehouse:
    name = name.strip()
    existing = db.scalar(select(Warehouse).where(Warehouse.name == name))
    if existing:
        raise AppError("Склад с таким именем уже есть", code="warehouse_exists", status_code=409)
    wh = Warehouse(name=name)
    db.add(wh)
    db.commit()
    db.refresh(wh)
    return wh


def rename_warehouse(db: Session, warehouse_id: uuid.UUID, name: str) -> Warehouse:
    wh = db.get(Warehouse, warehouse_id)
    if wh is None:
        raise AppError("Склад не найден", code="warehouse_not_found", status_code=404)
    if wh.is_deleted:
        raise AppError("Нельзя переименовать удалённый склад", code="warehouse_deleted")

    name = name.strip()
    clash = db.scalar(select(Warehouse).where(Warehouse.name == name, Warehouse.id != warehouse_id))
    if clash:
        raise AppError("Склад с таким именем уже есть", code="warehouse_exists", status_code=409)

    wh.name = name
    db.commit()
    db.refresh(wh)
    return wh


def soft_delete_warehouse(db: Session, warehouse_id: uuid.UUID, idempotency_key: str) -> dict:
    """Мягкое удаление: остатки и история сохраняются, товар числится на удалённом ФФ."""
    existing = find_operation(db, idempotency_key)
    if existing:
        return {
            "replayed": True,
            "operation_id": existing.id,
            "entity_id": existing.from_warehouse_id,
            "detail": "Повторное подтверждение: склад уже удалён",
        }

    wh = db.get(Warehouse, warehouse_id)
    if wh is None:
        raise AppError("Склад не найден", code="warehouse_not_found", status_code=404)
    if wh.is_deleted:
        raise AppError("Склад уже удалён", code="already_deleted")

    wh.is_deleted = True
    wh.deleted_at = datetime.now(timezone.utc)

    op = Operation(
        idempotency_key=idempotency_key,
        type=OperationType.WAREHOUSE_SOFT_DELETE,
        from_warehouse_id=wh.id,
        quantity=0,
        note=f"Склад «{wh.name}» удалён. Остатки и история сохранены, товар числится на удалённом ФФ.",
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return {
        "replayed": False,
        "operation_id": op.id,
        "entity_id": wh.id,
        "detail": op.note,
    }
