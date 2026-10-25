"""Receipts and links attached to a period (DOMAIN §10)."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.attachment import Attachment
from app.models.audit_event import AuditEvent
from tests.helpers import ADMIN, bearer, create_recurring, create_user, freeze, login
from tests.test_contract import check

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.7\n" + b"0" * 64
ATT = "/payment-occurrences/{id}/attachments"


@pytest.fixture(autouse=True)
def storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "attachments_dir", tmp_path)
    return tmp_path


@pytest.fixture
async def world(client: AsyncClient, db: AsyncSession) -> dict:
    freeze("2026-11-01T12:00:00+03:00")
    admin = bearer(await login(client, *ADMIN))
    await create_user(db, "anna", "anna-password")
    await create_user(db, "boris", "boris-password")
    anna = bearer(await login(client, "anna", "anna-password"))
    boris = bearer(await login(client, "boris", "boris-password"))
    client.cookies.clear()
    rp = await create_recurring(client, admin, "2026-11-10")
    occ = (
        await client.get("/api/v1/payment-occurrences", headers=anna, params={"sort": "due_date"})
    ).json()["items"]
    return {"admin": admin, "anna": anna, "boris": boris, "rp": rp, "occ": occ[0], "next": occ[1]}


def _files(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _url(occ_id: int) -> str:
    return "/api/v1" + ATT.format(id=occ_id)


async def _upload(client: AsyncClient, h: dict, occ_id: int, content: bytes, name: str = "чек.png"):
    return await client.post(_url(occ_id), files={"file": (name, content, "image/png")}, headers=h)


async def _link(client: AsyncClient, h: dict, occ_id: int, **body):
    return await client.post(
        _url(occ_id), json={"url": "https://bank.example/receipt/1", **body}, headers=h
    )


@pytest.mark.parametrize(
    ("content", "kind"), [(PNG, "image/png"), (JPEG, "image/jpeg"), (PDF, "application/pdf")]
)
async def test_upload_and_download(
    client: AsyncClient, world: dict, storage: Path, content: bytes, kind: str
) -> None:
    occ_id = world["occ"]["id"]  # unpaid period: allowed (e.g. an invoice)
    r = await _upload(client, world["anna"], occ_id, content, name="Чек за ноябрь.bin")
    body = check(ATT, "post", r)
    assert r.status_code == 201
    assert body["kind"] == "file" and body["content_type"] == kind  # by signature, not by name
    assert body["size_bytes"] == len(content) and body["file_name"] == "Чек за ноябрь.bin"
    assert body["url"] == f"/api/v1/attachments/{body['id']}/file"
    assert body["created_by"]["login"] == "anna"
    [stored] = _files(storage)
    assert len(stored.name) == 32 and _read(stored) == content  # UUID name on disk

    r = await client.get(body["url"], headers=world["boris"])
    assert r.status_code == 200 and r.content == content
    assert r.headers["content-type"].startswith(kind)
    assert r.headers["content-disposition"].startswith("attachment;")
    assert "filename*=utf-8''" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (await client.get(body["url"])).status_code == 401

    occ = (await client.get(f"/api/v1/payment-occurrences/{occ_id}", headers=world["anna"])).json()
    assert occ["attachments_count"] == 1
    listed = check(ATT, "get", await client.get(_url(occ_id), headers=world["boris"]))
    assert [a["id"] for a in listed] == [body["id"]]


@pytest.mark.parametrize(
    ("content", "field"),
    [
        (b"GIF89a" + b"\x00" * 10, "file"),
        (b"MZ\x90\x00 this is an exe", "file"),
        (b"", "file"),
        (b"<html><script>alert(1)</script>", "file"),
    ],
)
async def test_rejected_files(
    client: AsyncClient, world: dict, storage: Path, content: bytes, field: str
) -> None:
    r = await _upload(client, world["anna"], world["occ"]["id"], content, name="fake.png")
    body = check(ATT, "post", r)
    assert r.status_code == 422 and body["error"]["details"][0]["field"] == field
    assert _files(storage) == []


async def test_file_over_10_mb_is_413(client: AsyncClient, world: dict, storage: Path) -> None:
    big = PNG + b"\x00" * (10 * 1024 * 1024)
    r = await _upload(client, world["anna"], world["occ"]["id"], big)
    assert check(ATT, "post", r)["error"]["code"] == "payload_too_large"
    assert _files(storage) == []
    exact = b"%PDF-" + b"0" * (10 * 1024 * 1024 - 5)
    assert (await _upload(client, world["anna"], world["occ"]["id"], exact)).status_code == 201


async def test_path_in_file_name_is_dropped(
    client: AsyncClient, world: dict, storage: Path
) -> None:
    r = await _upload(client, world["anna"], world["occ"]["id"], PDF, name="../../etc/passwd.pdf")
    assert r.json()["file_name"] == "passwd.pdf"
    [stored] = _files(storage)
    assert stored.parent == storage


async def test_links(client: AsyncClient, world: dict) -> None:
    occ_id = world["occ"]["id"]
    r = await _link(client, world["anna"], occ_id, title="  Квитанция  ")
    body = check(ATT, "post", r)
    assert body["kind"] == "link" and body["url"] == "https://bank.example/receipt/1"
    assert body["title"] == "Квитанция" and body["file_name"] is None and body["size_bytes"] is None
    assert (
        await client.get(f"/api/v1/attachments/{body['id']}/file", headers=world["anna"])
    ).status_code == 404
    for bad in [
        {"url": "javascript:alert(1)"},
        {"url": "ftp://files.example/x"},
        {"url": "https://"},
        {"url": "https://a.example/" + "x" * 2048},
        {"url": "https://a.example", "title": "т" * 101},
        {},
    ]:
        r = await client.post(_url(occ_id), json=bad, headers=world["anna"])
        assert check(ATT, "post", r)["error"]["code"] == "validation_error", bad
    r = await client.post(
        _url(occ_id), json={"url": "https://a.example", "x": 1}, headers=world["anna"]
    )
    assert r.json()["error"]["code"] == "field_not_allowed"
    r = await client.post(
        _url(occ_id), content=b"hello", headers={**world["anna"], "Content-Type": "text/plain"}
    )
    assert r.status_code == 422


async def test_limit_5_per_period(client: AsyncClient, world: dict) -> None:
    occ_id = world["occ"]["id"]
    for n in range(3):
        assert (await _link(client, world["anna"], occ_id, title=f"#{n}")).status_code == 201
    for _ in range(2):
        assert (await _upload(client, world["boris"], occ_id, PNG)).status_code == 201
    r = await _link(client, world["admin"], occ_id)
    assert check(ATT, "post", r)["error"]["code"] == "attachments_limit"
    assert (await _upload(client, world["admin"], world["next"]["id"], PNG)).status_code == 201


async def test_delete_rights_and_file_removal(
    client: AsyncClient, db: AsyncSession, world: dict, storage: Path
) -> None:
    occ_id = world["occ"]["id"]
    mine = (await _upload(client, world["anna"], occ_id, PNG)).json()
    other = (await _link(client, world["anna"], occ_id)).json()

    r = await client.delete(f"/api/v1/attachments/{mine['id']}", headers=world["boris"])
    assert check("/attachments/{id}", "delete", r)["error"]["code"] == "forbidden"
    r = await client.delete(f"/api/v1/attachments/{mine['id']}", headers=world["anna"])
    check("/attachments/{id}", "delete", r)
    assert _files(storage) == []
    assert (await client.get(mine["url"], headers=world["anna"])).status_code == 404
    r = await client.delete(
        f"/api/v1/attachments/{other['id']}", headers=world["admin"]
    )  # admin may
    assert r.status_code == 204
    check(
        "/attachments/{id}",
        "delete",
        await client.delete(f"/api/v1/attachments/{other['id']}", headers=world["admin"]),
    )

    actions = (
        await db.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.action.like("attachment.%"))
            .order_by(AuditEvent.id)
        )
    ).all()
    assert actions == ["attachment.add", "attachment.add", "attachment.delete", "attachment.delete"]


async def test_unknown_period(client: AsyncClient, world: dict) -> None:
    check(ATT, "get", await client.get(_url(9999), headers=world["anna"]))
    check(ATT, "post", await _upload(client, world["anna"], 9999, PNG))
    check(ATT, "post", await client.post(_url(1)))  # 401


async def test_stop_removes_files_of_deleted_future_periods(
    client: AsyncClient, db: AsyncSession, world: dict, storage: Path
) -> None:
    await _upload(client, world["anna"], world["occ"]["id"], PNG)  # due 11-10, future → deleted
    r = await client.delete(
        f"/api/v1/recurring-payments/{world['rp']['id']}", headers=world["admin"]
    )
    assert r.status_code == 200
    assert _files(storage) == []
    assert (await db.scalars(select(Attachment))).all() == []
