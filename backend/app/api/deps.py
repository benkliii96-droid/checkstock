from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.services.errors import AppError


def raise_app_error(exc: AppError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, **exc.details},
    )


def app_error_response(exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, **exc.details},
    )
