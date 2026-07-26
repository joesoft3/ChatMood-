"""🔑 Developer API keys + the public OpenAI-compatible API.

The security claims under test: the plaintext key is shown exactly once, only a
hash is stored, revocation is immediate, scopes are enforced, and a session JWT
cannot be used as an API key (or vice versa).
"""

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import ApiKey, Base
from app.db.session import get_db
from app.main import app
from app.services.apikeys import clean_scopes, generate_key, has_scope, hash_key, looks_like_key

PW = "ApiKeys-2026!"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def env(monkeypatch):
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
    monkeypatch.setattr(settings, "PUBLIC_API_ENABLED", True)
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


# ---------- pure helpers ----------

def test_generated_keys_are_unique_prefixed_and_hashed():
    a, prefix_a, hash_a = generate_key()
    b, _, hash_b = generate_key()
    assert a.startswith("mk_live_") and a != b and hash_a != hash_b
    assert prefix_a == a[:11] and len(hash_a) == 64
    assert hash_key(a) == hash_a  # deterministic


def test_looks_like_key_screens_out_jwts_cheaply():
    secret, _, _ = generate_key()
    assert looks_like_key(secret) is True
    assert looks_like_key("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def") is False
    assert looks_like_key("") is False
    assert looks_like_key(None) is False
    assert looks_like_key("mk_live_short") is False  # too short to be real


def test_scope_normalization_is_forgiving_but_bounded():
    assert clean_scopes("chat,images") == "chat,images"
    assert clean_scopes(["IMAGES", " chat "]) == "chat,images"  # case/space tolerant, sorted
    assert clean_scopes("chat,chat") == "chat"  # deduped
    # unknown scopes are dropped, not fatal; an empty result never yields an inert key
    assert clean_scopes("chat,telepathy") == "chat"
    assert clean_scopes("telepathy") == "chat,search"
    assert clean_scopes(None) == "chat,search"


def test_has_scope_checks_exact_membership():
    assert has_scope("chat,search", "chat") is True
    assert has_scope("chat,search", "images") is False
    assert has_scope("", "chat") is False
    assert has_scope(None, "chat") is False


# ---------- key management ----------

def test_key_is_returned_once_and_only_its_hash_is_stored(env):
    async def go():
        factory = env
        async with await _client() as c:
            tok = await _token(c, "k1@test.io")
            r = await c.post("/keys", json={"name": "CI bot", "scopes": ["chat"]}, headers=_h(tok))
            assert r.status_code == 201, r.text
            secret = r.json()["key"]
            assert secret.startswith("mk_live_")
            assert "never be shown again" in r.json()["warning"]

            # listing never exposes the secret again
            listing = (await c.get("/keys", headers=_h(tok))).json()
            assert len(listing["keys"]) == 1
            assert "key" not in listing["keys"][0]
            assert listing["keys"][0]["prefix"] == secret[:11]

            # the database holds a hash, never the plaintext
            async with factory() as s:
                row = (await s.execute(select(ApiKey))).scalar_one()
                assert row.key_hash == hash_key(secret)
                assert secret not in json.dumps(
                    {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}
                )

    run(go())


def test_key_limit_and_revocation(env, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY_MAX_PER_USER", 2)

    async def go():
        async with await _client() as c:
            tok = await _token(c, "k2@test.io")
            first = (await c.post("/keys", json={"name": "a"}, headers=_h(tok))).json()
            await c.post("/keys", json={"name": "b"}, headers=_h(tok))
            r = await c.post("/keys", json={"name": "c"}, headers=_h(tok))
            assert r.status_code == 400 and "revoke one first" in r.json()["detail"]

            # revoking frees a slot, and the row survives for the audit trail
            assert (await c.delete(f"/keys/{first['id']}", headers=_h(tok))).status_code == 200
            assert (await c.post("/keys", json={"name": "c"}, headers=_h(tok))).status_code == 201
            keys = (await c.get("/keys", headers=_h(tok))).json()["keys"]
            assert any(k["revoked"] for k in keys) and len(keys) == 3

    run(go())


def test_keys_are_private_to_their_owner(env):
    async def go():
        async with await _client() as c:
            a = await _token(c, "ka@test.io")
            b = await _token(c, "kb@test.io")
            kid = (await c.post("/keys", json={"name": "mine"}, headers=_h(a))).json()["id"]
            assert (await c.delete(f"/keys/{kid}", headers=_h(b))).status_code == 404
            assert (await c.get("/keys", headers=_h(b))).json()["keys"] == []

    run(go())


# ---------- public API auth ----------

async def _mint(c, email="dev@test.io", scopes=("chat", "search", "images")):
    tok = await _token(c, email)
    r = await c.post("/keys", json={"name": "sdk", "scopes": list(scopes)}, headers=_h(tok))
    return r.json()["key"], tok


def test_public_api_accepts_a_key_and_rejects_a_session_jwt(env):
    async def go():
        async with await _client() as c:
            key, jwt = await _mint(c, "auth1@test.io")

            assert (await c.get("/public/models", headers=_h(key))).status_code == 200
            # a browser JWT is deliberately NOT valid on the developer surface
            r = await c.get("/public/models", headers=_h(jwt))
            assert r.status_code == 401 and "API key" in r.json()["detail"]
            # and a garbage key is rejected too
            assert (await c.get("/public/models", headers=_h("mk_live_" + "z" * 40))).status_code == 401

    run(go())


def test_revoked_key_stops_working_immediately(env):
    async def go():
        async with await _client() as c:
            tok = await _token(c, "rev@test.io")
            created = (await c.post("/keys", json={"name": "temp"}, headers=_h(tok))).json()
            key = created["key"]
            assert (await c.get("/public/models", headers=_h(key))).status_code == 200

            await c.delete(f"/keys/{created['id']}", headers=_h(tok))
            assert (await c.get("/public/models", headers=_h(key))).status_code == 401

    run(go())


def test_key_usage_counters_advance(env):
    async def go():
        async with await _client() as c:
            key, tok = await _mint(c, "count@test.io")
            for _ in range(3):
                await c.get("/public/models", headers=_h(key))
            row = (await c.get("/keys", headers=_h(tok))).json()["keys"][0]
            assert row["calls"] >= 3 and row["last_used_at"] is not None

    run(go())


def test_scopes_are_enforced_per_endpoint(env, monkeypatch):
    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "scope@test.io", scopes=("chat",))
            # /search needs the search scope
            r = await c.post("/public/search", json={"query": "hello"}, headers=_h(key))
            assert r.status_code == 403 and "search" in r.json()["detail"]
            # /images needs the images scope
            r = await c.post("/public/images", json={"prompt": "a cat"}, headers=_h(key))
            assert r.status_code == 403 and "images" in r.json()["detail"]

    run(go())


# ---------- OpenAI-compatible surface ----------

def _stub_llm(monkeypatch, text="Hello from Mood."):
    from app.services import llm as llm_mod

    async def fake_complete(messages, model=None, temperature=0.3, max_tokens=None, usage_out=None, provider=None):
        if usage_out is not None:
            usage_out.update({"prompt_tokens": 12, "completion_tokens": 4})
        return text

    async def fake_search(messages, model=None, temperature=0.4, usage_out=None, provider=None):
        if usage_out is not None:
            usage_out.update({"prompt_tokens": 3, "completion_tokens": 5})
        return text, ["https://example.com/x"]

    async def fake_stream(messages, model, enable_search=False, provider=None, think=False):
        for piece in ["Hel", "lo!"]:
            yield {"type": "delta", "text": piece}
        yield {"type": "usage", "usage": {"prompt_tokens": 2, "completion_tokens": 2}}

    monkeypatch.setattr(llm_mod.llm, "complete", fake_complete)
    monkeypatch.setattr(llm_mod.llm, "complete_with_search", fake_search)
    monkeypatch.setattr(llm_mod.llm, "stream_chat", fake_stream)


def test_models_endpoint_returns_the_openai_list_shape(env):
    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "models@test.io")
            body = (await c.get("/public/models", headers=_h(key))).json()
            assert body["object"] == "list"
            ids = [m["id"] for m in body["data"]]
            assert "mood-flagship" in ids and "mood-fast" in ids
            assert all(m["object"] == "model" for m in body["data"])

    run(go())


def test_chat_completion_matches_the_openai_envelope(env, monkeypatch):
    _stub_llm(monkeypatch, "42.")

    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "cc@test.io")
            r = await c.post(
                "/public/chat/completions",
                json={"model": "mood-flagship", "messages": [{"role": "user", "content": "meaning?"}]},
                headers=_h(key),
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["object"] == "chat.completion"
            assert body["id"].startswith("chatcmpl-")
            assert body["model"] == "mood-flagship"
            choice = body["choices"][0]
            assert choice["message"] == {"role": "assistant", "content": "42."}
            assert choice["finish_reason"] == "stop"
            assert body["usage"] == {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16}

    run(go())


def test_streaming_completion_emits_chunk_frames_and_done(env, monkeypatch):
    _stub_llm(monkeypatch)

    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "stream@test.io")
            async with c.stream(
                "POST",
                "/public/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
                headers=_h(key),
            ) as resp:
                assert resp.status_code == 200
                raw = "".join([chunk async for chunk in resp.aiter_text()])

            frames = [ln[6:] for ln in raw.splitlines() if ln.startswith("data: ")]
            assert frames[-1] == "[DONE]"
            parsed = [json.loads(f) for f in frames[:-1]]
            assert all(p["object"] == "chat.completion.chunk" for p in parsed)
            text = "".join(p["choices"][0]["delta"].get("content", "") for p in parsed)
            assert text == "Hello!"
            assert parsed[-1]["choices"][0]["finish_reason"] == "stop"

    run(go())


def test_unknown_model_alias_falls_back_instead_of_erroring(env, monkeypatch):
    _stub_llm(monkeypatch)

    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "alias@test.io")
            r = await c.post(
                "/public/chat/completions",
                json={"model": "mood-retired-v0", "messages": [{"role": "user", "content": "hi"}]},
                headers=_h(key),
            )
            assert r.status_code == 200  # an old pinned name must not break an integration

    run(go())


def test_search_endpoint_returns_answer_plus_citations(env, monkeypatch):
    _stub_llm(monkeypatch, "The answer.")

    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "srch@test.io")
            r = await c.post("/public/search", json={"query": "who won?"}, headers=_h(key))
            assert r.status_code == 200
            assert r.json()["answer"] == "The answer."
            assert r.json()["citations"] == ["https://example.com/x"]

    run(go())


def test_upstream_failure_becomes_a_clean_502(env, monkeypatch):
    from app.services import llm as llm_mod

    async def boom(*a, **k):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(llm_mod.llm, "complete", boom)

    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "boom@test.io")
            r = await c.post(
                "/public/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_h(key),
            )
            assert r.status_code == 502 and r.json()["detail"]

    run(go())


def test_public_api_calls_are_metered(env, monkeypatch):
    _stub_llm(monkeypatch)
    seen: list[tuple] = []

    async def fake_record(user_id, kind, model=None, **kw):
        seen.append((kind, kw.get("tokens_in"), kw.get("tokens_out")))

    import app.api.routes.public_api as papi

    monkeypatch.setattr(papi, "record_usage", fake_record)

    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "pmeter@test.io")
            await c.post(
                "/public/chat/completions",
                json={"messages": [{"role": "user", "content": "hi"}]},
                headers=_h(key),
            )

    run(go())
    assert seen and seen[0][0] == "api" and seen[0][1] == 12 and seen[0][2] == 4


def test_usage_endpoint_reports_the_owners_meters(env):
    async def go():
        async with await _client() as c:
            key, _ = await _mint(c, "usage@test.io")
            body = (await c.get("/public/usage", headers=_h(key))).json()
            assert body["plan"] == "free"
            assert "tokens_month" in body and "api_day" in body
            assert body["key"]["prefix"] == key[:11]

    run(go())


def test_public_api_can_be_disabled_by_config(env, monkeypatch):
    async def go():
        async with await _client() as c:
            key, tok = await _mint(c, "poff@test.io")
            monkeypatch.setattr(settings, "PUBLIC_API_ENABLED", False)
            assert (await c.get("/public/models", headers=_h(key))).status_code == 503
            assert (await c.get("/keys", headers=_h(tok))).status_code == 503

    run(go())
