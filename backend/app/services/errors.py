from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, code: str = "error", status_code: int = 400, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class ShortageError(AppError):
    def __init__(
        self,
        *,
        requested: int,
        available_on_selected: int,
        total_available: int,
        alternatives: list[dict],
        warehouse_name: str,
    ):
        message = (
            f"На складе «{warehouse_name}» доступно {available_on_selected}, запрошено {requested}. "
            f"Общий доступный остаток по всем ФФ: {total_available}."
        )
        super().__init__(
            message,
            code="insufficient_on_selected_warehouse",
            status_code=409,
            details={
                "requested": requested,
                "available_on_selected": available_on_selected,
                "total_available": total_available,
                "alternatives": alternatives,
            },
        )
