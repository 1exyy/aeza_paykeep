"""FastAPI application. All routes live under /api/v1; Swagger at /api/v1/docs."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging

API_PREFIX = "/api/v1"
SWAGGER_DIR = Path(__file__).resolve().parent / "static" / "swagger"


def load_contract(dev_mode: bool) -> dict[str, Any]:
    """The OpenAPI document served by Swagger is the agreed contract (docs/api/openapi.yaml).

    tests/test_contract.py checks that every contract operation is routed by the app and back,
    and validates responses against the contract schemas.
    """
    settings = get_settings()
    with open(settings.contract_path, encoding="utf-8") as f:
        spec: dict[str, Any] = yaml.safe_load(f)
    if not dev_mode:
        spec["paths"] = {p: v for p, v in spec["paths"].items() if not p.startswith("/dev/")}
    spec["servers"] = [{"url": API_PREFIX}]
    return spec


def install_swagger_ui(app: FastAPI) -> None:
    """Swagger UI at /api/v1/docs with assets vendored in app/static/swagger (see VERSION.md)."""
    static = f"{API_PREFIX}/docs/static"
    oauth2_redirect = f"{API_PREFIX}/docs/oauth2-redirect"
    app.mount(static, StaticFiles(directory=SWAGGER_DIR), name="swagger-static")

    @app.get(f"{API_PREFIX}/docs", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=f"{API_PREFIX}/openapi.json",
            title="Invoice Keeper API — Swagger",
            swagger_js_url=f"{static}/swagger-ui-bundle.js",
            swagger_css_url=f"{static}/swagger-ui.css",
            swagger_favicon_url=f"{static}/favicon-32x32.png",
            oauth2_redirect_url=oauth2_redirect,
            swagger_ui_parameters={"persistAuthorization": True},
        )

    @app.get(oauth2_redirect, include_in_schema=False)
    async def swagger_ui_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    from app.services.bootstrap import on_startup

    await on_startup()
    yield
    from app.channels.apply_bot import close_apply_bot

    await close_apply_bot()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    app = FastAPI(
        title="Invoice Keeper API",
        docs_url=None,  # served below with local Swagger UI assets (no CDN)
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    install_swagger_ui(app)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = load_contract(settings.dev_mode)
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
    return app


app = create_app()
