"""Сиды демо-магазина: два ФФ и количества прихода из тестового задания."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Operation, OperationType, Product, Warehouse
from app.services.stock import get_or_create_balance


SEED_WAREHOUSES = ["Север", "Юг"]
SEED_PRODUCTS = [
    ("SKU-101", "Органайзер"),
    ("SKU-102", "Контейнер"),
    ("SKU-103", "Корзина"),
]
# Стартовые приходы из брифа
SEED_RECEIPTS = {
    ("SKU-101", "Север"): 10,
    ("SKU-101", "Юг"): 6,
    ("SKU-102", "Север"): 5,
    ("SKU-102", "Юг"): 0,
    ("SKU-103", "Север"): 0,
    ("SKU-103", "Юг"): 4,
}


def seed_if_empty(db: Session) -> None:
    has_products = db.scalar(select(Product.id).limit(1))
    if has_products is not None:
        return

    warehouses: dict[str, Warehouse] = {}
    for name in SEED_WAREHOUSES:
        wh = Warehouse(name=name)
        db.add(wh)
        warehouses[name] = wh

    products: dict[str, Product] = {}
    for sku, name in SEED_PRODUCTS:
        product = Product(sku=sku, name=name)
        db.add(product)
        products[sku] = product

    db.flush()

    for (sku, wh_name), qty in SEED_RECEIPTS.items():
        product = products[sku]
        warehouse = warehouses[wh_name]
        bal = get_or_create_balance(db, warehouse.id, product.id)
        if qty > 0:
            bal.on_hand = qty
            db.add(
                Operation(
                    idempotency_key=f"seed-receipt-{sku}-{wh_name}",
                    type=OperationType.RECEIPT,
                    product_id=product.id,
                    quantity=qty,
                    to_warehouse_id=warehouse.id,
                    note=f"Стартовый приход {qty} шт. на «{wh_name}»",
                )
            )
        else:
            # Нулевые ячейки не создаём — в UI они всё равно отобразятся как 0
            pass

    db.commit()
