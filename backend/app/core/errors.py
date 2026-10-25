"""Contract error format: {"error": {"code", "message", "details"}} with Russian messages."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class AppError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: list[dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers

    @classmethod
    def validation(cls, field: str, message: str) -> "AppError":
        return cls(
            422,
            "validation_error",
            "Проверьте введённые данные",
            [{"field": field, "message": message}],
        )


def unauthorized() -> AppError:
    return AppError(401, "unauthorized", "Войдите снова")


def forbidden() -> AppError:
    return AppError(403, "forbidden", "Недостаточно прав")


def password_change_required() -> AppError:
    return AppError(
        403, "password_change_required", "Смените временный пароль, чтобы продолжить работу"
    )


def admin_protected() -> AppError:
    return AppError(403, "admin_protected", "Учётную запись администратора нельзя изменить")


def not_found(message: str = "Не найдено") -> AppError:
    return AppError(404, "not_found", message)


def version_conflict() -> AppError:
    return AppError(
        409, "version_conflict", "Запись изменена другим пользователем. Обновите данные"
    )


def error_body(code: str, message: str, details: list[dict[str, str]] | None = None) -> dict:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


_MESSAGES: dict[str, str] = {
    "missing": "Обязательное поле",
    "string_too_short": "Слишком короткое значение (минимум {min_length})",
    "string_too_long": "Слишком длинное значение (максимум {max_length})",
    "string_pattern_mismatch": "Недопустимый формат",
    "string_type": "Ожидается строка",
    "int_parsing": "Ожидается целое число",
    "int_type": "Ожидается целое число",
    "int_from_float": "Ожидается целое число",
    "greater_than": "Значение должно быть больше {gt}",
    "greater_than_equal": "Значение должно быть не меньше {ge}",
    "less_than": "Значение должно быть меньше {lt}",
    "less_than_equal": "Значение должно быть не больше {le}",
    "date_parsing": "Ожидается дата в формате ГГГГ-ММ-ДД",
    "date_from_datetime_parsing": "Ожидается дата в формате ГГГГ-ММ-ДД",
    "date_from_datetime_inexact": "Ожидается дата в формате ГГГГ-ММ-ДД",
    "date_type": "Ожидается дата в формате ГГГГ-ММ-ДД",
    "enum": "Недопустимое значение. Допустимо: {expected}",
    "literal_error": "Недопустимое значение. Допустимо: {expected}",
    "bool_parsing": "Ожидается true или false",
    "bool_type": "Ожидается true или false",
    "json_invalid": "Некорректный JSON",
    "model_attributes_type": "Ожидается JSON-объект",
    "dict_type": "Ожидается JSON-объект",
    "extra_forbidden": "Это поле нельзя передавать",
}

_LOCATIONS = {"body", "query", "path", "header", "cookie"}


def _field_name(loc: tuple[Any, ...]) -> str:
    parts = [str(p) for p in loc]
    if parts and parts[0] in _LOCATIONS:
        parts = parts[1:]
    return ".".join(parts) or "body"


def _message(err: dict[str, Any]) -> str:
    err_type = err.get("type", "")
    ctx = err.get("ctx") or {}
    if err_type == "value_error" and "error" in ctx:
        return str(ctx["error"])
    template = _MESSAGES.get(err_type)
    if template is None:
        return "Некорректное значение"
    if "expected" in ctx:
        ctx = {**ctx, "expected": str(ctx["expected"]).replace(" or ", ", ")}
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return template.split(" (")[0]


def validation_details(errors: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [{"field": _field_name(tuple(e.get("loc", ()))), "message": _message(e)} for e in errors]


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        error_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=exc.headers
    )


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = list(exc.errors())
    details = validation_details(errors)
    if any(e.get("type") == "extra_forbidden" for e in errors):
        body = error_body("field_not_allowed", "Это поле нельзя изменять", details)
    else:
        body = error_body("validation_error", "Проверьте введённые данные", details)
    return JSONResponse(body, status_code=422)


async def _http_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        body = error_body("not_found", "Ресурс не найден")
    elif exc.status_code == 405:
        # TODO(question): no code for 405 in the contract enum; propose adding method_not_allowed.
        body = error_body("method_not_allowed", "Метод не поддерживается для этого адреса")
    elif exc.status_code == 401:
        body = error_body("unauthorized", "Войдите снова")
    elif exc.status_code == 403:
        body = error_body("forbidden", "Недостаточно прав")
    else:
        body = error_body("internal_error", "Ошибка обработки запроса")
    return JSONResponse(body, status_code=exc.status_code, headers=getattr(exc, "headers", None))


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        error_body("internal_error", "Внутренняя ошибка сервера. Попробуйте позже"), status_code=500
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
