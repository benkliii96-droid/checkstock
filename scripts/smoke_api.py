"""Дымовые проверки против запущенного API (после docker compose up).

Запуск:
  python scripts/smoke_api.py
  python scripts/smoke_api.py http://localhost:8000
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid


def req(base: str, method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        payload = json.loads(raw) if raw else {}
        return exc.code, payload


def main() -> int:
    base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
    print(f"Smoke against {base}")

    code, health = req(base, "GET", "/api/health")
    assert code == 200 and health.get("status") == "ok", health
    print("OK health")

    code, stock = req(base, "GET", "/api/stock")
    assert code == 200, stock
    products = {p["sku"]: p for p in stock["products"]}
    assert "SKU-101" in products
    north = next(c for c in products["SKU-101"]["cells"] if c["warehouse_name"] == "Север")
    assert north["on_hand"] >= 10
    print("OK seed stock visible")

    # Идемпотентный приход
    product_id = products["SKU-102"]["product_id"]
    south = next(c for c in products["SKU-102"]["cells"] if c["warehouse_name"] == "Юг")
    key = f"smoke-receipt-{uuid.uuid4()}"
    body = {
        "idempotency_key": key,
        "product_id": product_id,
        "warehouse_id": south["warehouse_id"],
        "quantity": 1,
    }
    code1, r1 = req(base, "POST", "/api/movements/receipt", body)
    code2, r2 = req(base, "POST", "/api/movements/receipt", body)
    assert code1 == 200 and r1.get("replayed") is False, r1
    assert code2 == 200 and r2.get("replayed") is True, r2
    print("OK idempotent receipt")

    # Нехватка на выбранном складе при достаточном общем остатке
    code, stock2 = req(base, "GET", "/api/stock")
    assert code == 200, stock2
    sku102 = next(p for p in stock2["products"] if p["sku"] == "SKU-102")
    active = [c for c in sku102["cells"] if not c["warehouse_deleted"]]
    weak = min(active, key=lambda c: c["available"])
    qty = weak["available"] + 1
    assert sku102["total_available"] >= qty, "нужен достаточный общий остаток для сценария нехватки"
    code, err = req(
        base,
        "POST",
        "/api/fbs/reserve",
        {
            "idempotency_key": f"smoke-shortage-{uuid.uuid4()}",
            "product_id": product_id,
            "warehouse_id": weak["warehouse_id"],
            "quantity": qty,
        },
    )
    detail = err.get("detail", err)
    assert code == 409, err
    assert detail.get("code") == "insufficient_on_selected_warehouse", err
    print("OK shortage on selected FF")

    print("All smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
