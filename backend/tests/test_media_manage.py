"""⬇✏️🗑 Generated media must be downloadable, editable and deletable.

The bug this guards: `_persist_generated_media` archived every generation as a
FileAsset but THREW AWAY the id, so the only handle the client had was a
presigned URL that expires after IMAGE_PERSIST_TTL_S (7 days). After that the
"Download" button 404s, and there was never any way to delete a generation.
"""

import asyncio

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, FileAsset, User
from app.db.session import get_db
from app.main import app

PW = "Media-Manage-2026!"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def api(monkeypatch, tmp_path):
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    async def _make():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_make())
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "IMAGE_PERSIST", True)
    monkeypatch.setattr(settings, "WATERMARK_ENABLED", False)
    yield factory
    app.dependency_overrides.pop(get_db, None)
    asyncio.run(engine.dispose())


async def _client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1", timeout=30
    )


async def _token(c, email):
    await c.post("/auth/register", json={"email": email, "password": PW})
    r = await c.post("/auth/login", json={"email": email, "password": PW})
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _stub_image(monkeypatch):
    """Provider returns a data URL — exercises the real persistence path."""
    import base64

    from app.api.routes import chat as chatmod

    async def fake_image(prompt, **kw):
        return "data:image/png;base64," + base64.b64encode(PNG).decode()

    monkeypatch.setattr(chatmod.llm, "generate_image", fake_image)


# ────────────────────────────────────────── the archived handle

def test_generated_image_returns_a_stable_file_id(api, monkeypatch):
    """Without this id the client only has an expiring presigned URL."""
    _stub_image(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "gen1@test.io")
            r = await c.post("/chat/image", json={"prompt": "a red kite"}, headers=_h(tok))
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["file_id"], "generation must expose its FileAsset id"
            assert body["stored"] in ("local", "r2")

    run(go())


def test_the_file_id_resolves_to_a_real_downloadable_asset(api, monkeypatch):
    _stub_image(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "gen2@test.io")
            fid = (await c.post("/chat/image", json={"prompt": "x"}, headers=_h(tok))).json()["file_id"]

            r = await c.get(f"/files/{fid}/download", headers=_h(tok))
            assert r.status_code == 200
            assert r.content == PNG                      # the real bytes, not a redirect stub
            assert "attachment" in (r.headers.get("content-disposition") or "").lower()

    run(go())


def test_generated_media_appears_in_the_users_library(api, monkeypatch):
    _stub_image(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "gen3@test.io")
            fid = (await c.post("/chat/image", json={"prompt": "x"}, headers=_h(tok))).json()["file_id"]
            files = (await c.get("/files", headers=_h(tok))).json()
            assert any(f["id"] == fid for f in files)

    run(go())


# ───────────────────────────────────────────────────── delete

def test_deleting_a_generation_removes_the_row_and_the_bytes(api, monkeypatch):
    _stub_image(monkeypatch)

    async def go():
        factory = api
        async with await _client() as c:
            tok = await _token(c, "del1@test.io")
            fid = (await c.post("/chat/image", json={"prompt": "x"}, headers=_h(tok))).json()["file_id"]

            assert (await c.delete(f"/files/{fid}", headers=_h(tok))).status_code == 204
            async with factory() as s:
                assert await s.get(FileAsset, fid) is None
            assert (await c.get(f"/files/{fid}/download", headers=_h(tok))).status_code == 404

    run(go())


def test_a_user_cannot_download_or_delete_someone_elses_generation(api, monkeypatch):
    """The ownership boundary — a file id is guessable enough to matter."""
    _stub_image(monkeypatch)

    async def go():
        async with await _client() as c:
            owner = await _token(c, "owner-m@test.io")
            fid = (await c.post("/chat/image", json={"prompt": "x"}, headers=_h(owner))).json()["file_id"]

            intruder = await _token(c, "intruder-m@test.io")
            assert (await c.get(f"/files/{fid}/download", headers=_h(intruder))).status_code == 404
            assert (await c.delete(f"/files/{fid}", headers=_h(intruder))).status_code == 404
            # ...and the owner's file is untouched
            assert (await c.get(f"/files/{fid}/download", headers=_h(owner))).status_code == 200

    run(go())


def test_download_and_delete_require_authentication(api, monkeypatch):
    _stub_image(monkeypatch)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "anon-m@test.io")
            fid = (await c.post("/chat/image", json={"prompt": "x"}, headers=_h(tok))).json()["file_id"]
            assert (await c.get(f"/files/{fid}/download")).status_code in (401, 403)
            assert (await c.delete(f"/files/{fid}")).status_code in (401, 403)

    run(go())


# ────────────────────────────────────────────── fail-open contract

def test_persistence_failure_still_returns_a_usable_generation(api, monkeypatch):
    """A generation must never fail because archiving did — the user just
    loses the manage actions (file_id is empty and the UI hides them)."""
    from app.api.routes import chat as chatmod

    _stub_image(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("storage down")

    monkeypatch.setattr("app.services.storage.put_upload", boom)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "failopen-m@test.io")
            r = await c.post("/chat/image", json={"prompt": "x"}, headers=_h(tok))
            assert r.status_code == 200
            assert r.json()["stored"] == "hotlink"
            assert r.json()["file_id"] == ""   # no handle → client hides manage actions
            assert r.json()["url"]             # but the image still renders

    run(go())


def test_persist_disabled_returns_no_file_id(api, monkeypatch):
    _stub_image(monkeypatch)
    monkeypatch.setattr(settings, "IMAGE_PERSIST", False)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "nopersist@test.io")
            r = await c.post("/chat/image", json={"prompt": "x"}, headers=_h(tok))
            assert r.json()["stored"] == "hotlink" and r.json()["file_id"] == ""

    run(go())
