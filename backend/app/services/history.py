from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Operation
from app.schemas import OperationOut


def list_operations(db: Session, limit: int = 100) -> list[OperationOut]:
    ops = db.scalars(
        select(Operation)
        .options(
            joinedload(Operation.product),
            joinedload(Operation.from_warehouse),
            joinedload(Operation.to_warehouse),
        )
        .order_by(Operation.created_at.desc())
        .limit(limit)
    ).all()

    result: list[OperationOut] = []
    for op in ops:
        result.append(
            OperationOut(
                id=op.id,
                idempotency_key=op.idempotency_key,
                type=op.type.value,
                product_sku=op.product.sku if op.product else None,
                product_name=op.product.name if op.product else None,
                quantity=op.quantity,
                from_warehouse=op.from_warehouse.name if op.from_warehouse else None,
                to_warehouse=op.to_warehouse.name if op.to_warehouse else None,
                related_entity_id=op.related_entity_id,
                note=op.note,
                created_at=op.created_at,
            )
        )
    return result
