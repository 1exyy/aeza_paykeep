"""Error format of the contract for framework-level errors."""

from fastapi import Body, Query
from httpx import AsyncClient

from app.main import app


@app.get("/api/v1/__test__/boom", include_in_schema=False)
async def _boom() -> None:
    raise RuntimeError("secret-token-123 must not leak")


@app.post("/api/v1/__test__/validate", include_in_schema=False)
async def _validate(limit: int = Query(ge=1, le=200), name: str = Body(min_length=3, embed=True)):
    return {"ok": True}


async def test_unknown_path_is_json_404(client: AsyncClient) -> None:
    r = await client.get("/api/v1/no-such-path")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Ресурс не найден"}}


async def test_wrong_method_is_json_405(client: AsyncClient) -> None:
    r = await client.delete("/api/v1/__test__/boom")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "method_not_allowed"


async def test_validation_error_format(client: AsyncClient) -> None:
    r = await client.post("/api/v1/__test__/validate?limit=500", json={"name": "a"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["message"] == "Проверьте введённые данные"
    fields = {d["field"]: d["message"] for d in err["details"]}
    assert fields == {
        "limit": "Значение должно быть не больше 200",
        "name": "Слишком короткое значение (минимум 3)",
    }


async def test_unhandled_error_is_500_without_stacktrace(client: AsyncClient) -> None:
    r = await client.get("/api/v1/__test__/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret-token" not in r.text
    assert "Traceback" not in r.text


async def test_swagger_and_contract_served(client: AsyncClient) -> None:
    r = await client.get("/api/v1/docs")
    assert r.status_code == 200
    assert "swagger" in r.text.lower()
    assert "cdn.jsdelivr.net" not in r.text and "https://" not in r.text
    for asset, kind in [
        ("swagger-ui-bundle.js", "javascript"),
        ("swagger-ui.css", "text/css"),
        ("favicon-32x32.png", "image/png"),
    ]:
        url = f"/api/v1/docs/static/{asset}"
        assert url in r.text
        static = await client.get(url)
        assert static.status_code == 200 and kind in static.headers["content-type"]
    assert (await client.get("/api/v1/docs/oauth2-redirect")).status_code == 200
    assert (await client.get("/api/v1/docs/static/nope.js")).json()["error"]["code"] == "not_found"
    spec = (await client.get("/api/v1/openapi.json")).json()
    assert spec["servers"] == [{"url": "/api/v1"}]
    assert "/auth/login" in spec["paths"]
