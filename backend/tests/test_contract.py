"""App matches docs/api/openapi.yaml: same (path, method) set; responses valid by its schemas."""

from datetime import date
from typing import Any

import pytest
import yaml
from fastapi.openapi.utils import get_openapi
from httpx import AsyncClient, Response
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.main import API_PREFIX, app
from tests.helpers import (
    ADMIN,
    bearer,
    create_recurring,
    create_user,
    freeze,
    login,
    set_business_today,
)

with open(get_settings().contract_path, encoding="utf-8") as f:
    CONTRACT: dict[str, Any] = yaml.safe_load(f)

METHODS = {"get", "post", "put", "patch", "delete"}

# Contract operations that are not implemented. Remove a line when one is.
NOT_YET_IMPLEMENTED = {
    ("/auth/telegram", "post"),  # optional, not implemented
}


def contract_ops() -> set[tuple[str, str]]:
    return {(p, m) for p, item in CONTRACT["paths"].items() for m in item if m in METHODS}


def app_ops() -> set[tuple[str, str]]:
    """Operations actually routed by the app (FastAPI's own generated schema)."""
    generated = get_openapi(title="check", version="0", routes=app.routes)
    ops = set()
    for path, item in generated["paths"].items():
        assert path.startswith(API_PREFIX), path
        ops |= {(path.removeprefix(API_PREFIX), m) for m in item if m in METHODS}
    return ops


def test_every_app_route_is_in_contract() -> None:
    assert app_ops() - contract_ops() == set()


def test_every_contract_operation_is_routed() -> None:
    assert contract_ops() - app_ops() == NOT_YET_IMPLEMENTED


def test_all_required_pdf_operations_are_routed() -> None:
    required = {
        (p, m)
        for p, item in CONTRACT["paths"].items()
        for m, op in item.items()
        if m in METHODS and op.get("x-required")
    }
    assert len(required) == 14  # + Swagger /api/v1/docs = 15 rows of the PDF table
    assert required <= app_ops()


def test_served_schema_is_the_contract() -> None:
    served = app.openapi()
    assert served["info"]["version"] == CONTRACT["info"]["version"]
    assert set(served["paths"]) == set(CONTRACT["paths"])  # DEV_MODE=true in tests


# ---------- response validation ----------


def _resolve(node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        target: Any = CONTRACT
        for part in node["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        node = target
    return node


def check(path: str, method: str, response: Response) -> Any:
    """Validate the response body by the contract's schema for this status code."""
    op = CONTRACT["paths"][path][method]
    status = str(response.status_code)
    assert status in op["responses"], f"{method.upper()} {path}: undocumented {status}"
    spec = _resolve(op["responses"][status])
    content = spec.get("content", {}).get("application/json")
    if content is None:
        assert not response.content, f"{method.upper()} {path} {status} must have no body"
        return None
    schema = {**content["schema"], "components": CONTRACT["components"]}
    body = response.json()
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(body),
        key=lambda e: list(e.path),
    )
    assert not errors, f"{method.upper()} {path} {status}: " + "; ".join(
        f"{list(e.path)}: {e.message}" for e in errors[:5]
    )
    return body


@pytest.fixture
async def world(client: AsyncClient, db: AsyncSession) -> dict:
    freeze("2026-11-01T12:00:00+03:00")
    admin = bearer(await login(client, *ADMIN))
    await create_user(db, "anna", "anna-password")
    anna = bearer(await login(client, "anna", "anna-password"))
    client.cookies.clear()
    return {"admin": admin, "anna": anna}


async def test_auth_responses(client: AsyncClient, world: dict) -> None:
    check(
        "/auth/login",
        "post",
        await client.post(
            "/api/v1/auth/login",
            json={"team": "aeza", "login": "anna", "password": "anna-password"},
        ),
    )
    client.cookies.clear()
    check(
        "/auth/login",
        "post",
        await client.post(
            "/api/v1/auth/login", json={"team": "aeza", "login": "anna", "password": "wrong"}
        ),
    )
    check("/auth/login", "post", await client.post("/api/v1/auth/login", json={}))
    check("/auth/me", "get", await client.get("/api/v1/auth/me", headers=world["anna"]))
    check("/auth/me", "get", await client.get("/api/v1/auth/me"))
    check("/auth/logout", "post", await client.post("/api/v1/auth/logout"))
    check("/config", "get", await client.get("/api/v1/config", headers=world["anna"]))
    for _ in range(5):
        await client.post(
            "/api/v1/auth/login", json={"team": "aeza", "login": "boris", "password": "x"}
        )
    check(
        "/auth/login",
        "post",
        await client.post(
            "/api/v1/auth/login", json={"team": "aeza", "login": "boris", "password": "x"}
        ),
    )  # 429
    # fmt: skip


async def test_users_responses(client: AsyncClient, world: dict) -> None:
    a, u = world["admin"], world["anna"]
    created = check(
        "/users",
        "post",
        await client.post(
            "/api/v1/users", json={"login": "boris", "password": "boris-password"}, headers=a
        ),
    )
    check(
        "/users",
        "post",
        await client.post(
            "/api/v1/users", json={"login": "boris", "password": "boris-password"}, headers=a
        ),
    )  # 409
    check(
        "/users",
        "post",
        await client.post("/api/v1/users", json={"login": "x", "password": "y"}, headers=a),
    )  # 422
    check(
        "/users",
        "post",
        await client.post(
            "/api/v1/users", json={"login": "eve", "password": "eve-password"}, headers=u
        ),
    )  # 403
    check("/users", "get", await client.get("/api/v1/users", headers=a))
    uid = created["id"]
    check(
        "/users/{id}",
        "patch",
        await client.patch(f"/api/v1/users/{uid}", json={"login": "boris2"}, headers=a),
    )
    check(
        "/users/{id}",
        "patch",
        await client.patch("/api/v1/users/9999", json={"login": "boris3"}, headers=a),
    )  # 404
    me = (await client.get("/api/v1/auth/me", headers=a)).json()
    body = check(
        "/users/{id}",
        "patch",
        await client.patch(f"/api/v1/users/{me['id']}", json={"login": "root"}, headers=a),
    )  # 403
    assert body["error"]["code"] == "admin_protected"
    check("/users/{id}", "delete", await client.delete(f"/api/v1/users/{uid}", headers=a))
    check("/users/{id}", "delete", await client.delete(f"/api/v1/users/{uid}", headers=a))
    # fmt: skip


async def test_payment_responses(client: AsyncClient, db: AsyncSession, world: dict) -> None:
    a, u = world["admin"], world["anna"]
    rp = await create_recurring(client, a, "2026-11-10")
    check(
        "/recurring-payments",
        "post",
        await client.post("/api/v1/recurring-payments", json={"title": ""}, headers=a),
    )  # 422
    check("/recurring-payments", "get", await client.get("/api/v1/recurring-payments", headers=u))
    items = check(
        "/payment-occurrences",
        "get",
        await client.get("/api/v1/payment-occurrences", headers=u, params={"sort": "due_date"}),
    )["items"]
    occ_id = items[0]["id"]
    await set_business_today(db, date(2026, 11, 12))
    check(
        "/payment-occurrences/{id}",
        "get",
        await client.get(f"/api/v1/payment-occurrences/{occ_id}", headers=u),
    )
    check(
        "/payment-occurrences/{id}",
        "get",
        await client.get("/api/v1/payment-occurrences/9999", headers=u),
    )  # 404
    patched = check(
        "/payment-occurrences/{id}",
        "patch",
        await client.patch(
            f"/api/v1/payment-occurrences/{occ_id}",
            json={"status": "paid", "paid_date": "2026-11-12"},
            headers=u,
        ),
    )
    assert patched["state"] == "paid_late" and patched["paid_by"]["login"] == "anna"
    check(
        "/payment-occurrences/{id}",
        "patch",
        await client.patch(
            f"/api/v1/payment-occurrences/{items[1]['id']}",
            json={"paid_date": "2026-11-12"},
            headers=u,
        ),
    )  # 409 not_paid
    check(
        "/payment-occurrences/{id}",
        "patch",
        await client.patch(
            f"/api/v1/payment-occurrences/{occ_id}", json={"due_date": "2026-12-01"}, headers=u
        ),
    )
    check("/payments/summary", "get", await client.get("/api/v1/payments/summary", headers=u))
    check(
        "/payments/summary",
        "get",
        await client.get(
            "/api/v1/payments/summary", headers=u, params={"from": "2027-01-01", "to": "2026-01-01"}
        ),
    )
    check(
        "/recurring-payments/{id}",
        "delete",
        await client.delete(f"/api/v1/recurring-payments/{rp['id']}", headers=u),
    )  # 403
    stopped = check(
        "/recurring-payments/{id}",
        "delete",
        await client.delete(f"/api/v1/recurring-payments/{rp['id']}", headers=a),
    )
    assert stopped["status"] == "stopped"
    check(
        "/recurring-payments/{id}",
        "delete",
        await client.delete("/api/v1/recurring-payments/9999", headers=a),
    )  # 404
    check("/payment-occurrences", "get", await client.get("/api/v1/payment-occurrences"))  # 401
    # fmt: skip
