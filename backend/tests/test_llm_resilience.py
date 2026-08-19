"""v1.9.1 — 🛟 LLM resilience: class-aware fallback mapping + instant sibling-bucket
rescue on 429 (no SDK backoff sleeps inside the stand-in stack)."""

import asyncio

import httpx
from openai import RateLimitError

from app.config import settings
from app.services.llm import llm


def _env(monkeypatch):
    monkeypatch.setattr(settings, "LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", "gemini-2.5-pro")
    monkeypatch.setattr(settings, "LLM_FALLBACK_429_SWAP", True)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gk")


def _rlerror() -> RateLimitError:
    req = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    return RateLimitError("quota exceeded", response=httpx.Response(429, request=req), body=None)


# ---------- class-aware failover mapping ----------

def test_flagship_goes_to_pro_bucket(monkeypatch):
    _env(monkeypatch)
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-2.5-pro")
    assert llm._failover("xai", "grok-4.1") == ("gemini", "gemini-2.5-pro")


def test_fast_and_mini_stay_on_flash_bucket(monkeypatch):
    _env(monkeypatch)
    assert llm._failover(None, "grok-4-fast") == ("gemini", "gemini-2.5-flash")
    assert llm._failover(None, "grok-3-mini") == ("gemini", "gemini-2.5-flash")
    assert llm._failover(None, "grok-code-fast-1") == ("gemini", "gemini-2.5-flash")


def test_pro_env_empty_falls_back_to_single_bucket(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODEL_PRO", "")
    assert llm._failover(None, "grok-4") == ("gemini", "gemini-2.5-flash")


# ---------- rescue-chain mapping ----------

def test_rescue_swaps_fallback_buckets_both_ways(monkeypatch):
    _env(monkeypatch)
    assert llm._rescue_chain("gemini", "gemini-2.5-flash") == [("gemini", "gemini-2.5-pro")]
    assert llm._rescue_chain("gemini", "gemini-2.5-pro") == [("gemini", "gemini-2.5-flash")]


def test_rescue_never_engages_outside_configured_providers(monkeypatch):
    _env(monkeypatch)
    assert llm._rescue_chain("xai", "grok-4") == []
    assert llm._rescue_chain(None, "grok-4") == []
    assert llm._rescue_chain("openai", "gpt-4o") == []


def test_rescue_respects_kill_switch(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(settings, "LLM_FALLBACK_429_SWAP", False)
    assert llm._rescue_chain("gemini", "gemini-2.5-flash") == []


# ---------- 429 rescue through complete() ----------

def test_complete_429_swims_to_sibling(monkeypatch):
    _env(monkeypatch)
    calls: list[str] = []

    class _Completions:
        async def create(self, model, messages, **kw):
            calls.append(model)
            if len(calls) == 1:
                raise _rlerror()
            class _Msg:
                content = "rescued by sibling"
            class _Choice:
                message = _Msg()
            class _Resp:
                choices = [_Choice()]
                usage = None
            return _Resp()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())
    out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}], model="grok-3-mini"))
    # grok-3-mini → flash bucket → 429 → rescued by pro bucket
    assert out == "rescued by sibling"
    assert calls == ["gemini-2.5-flash", "gemini-2.5-pro"]


def test_complete_429_raises_when_both_buckets_saturated(monkeypatch):
    _env(monkeypatch)
    calls: list[str] = []

    class _Completions:
        async def create(self, model, messages, **kw):
            calls.append(model)
            raise _rlerror()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())

    def _run():
        return asyncio.run(llm.complete([{"role": "user", "content": "hi"}], model="grok-3-mini"))

    try:
        _run()
        assert False, "expected RateLimitError"
    except RateLimitError:
        pass
    assert calls == ["gemini-2.5-flash", "gemini-2.5-pro"]  # exactly one rescue attempt


# ---------- 429 rescue through stream_chat() ----------

def test_stream_429_swims_to_sibling(monkeypatch):
    _env(monkeypatch)
    calls: list[str] = []

    class _Delta:
        content = "stream-rescued"
        reasoning_content = None

    class _Choice:
        delta = _Delta()

    class _Chunk:
        choices = [_Choice()]
        usage = None
        citations = None

    class _Stream:
        def __aiter__(self):
            async def gen():
                yield _Chunk()
            return gen()

    class _Completions:
        async def create(self, model, messages, **kw):
            calls.append(model)
            if len(calls) == 1:
                raise _rlerror()
            return _Stream()

    class _Client:
        class chat:
            completions = _Completions()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())

    async def _collect():
        out = []
        async for ev in llm.stream_chat([{"role": "user", "content": "hi"}], model="grok-4"):
            out.append(ev)
        return out

    events = asyncio.run(_collect())
    # grok-4 → pro bucket → 429 → rescued by flash bucket
    assert calls == ["gemini-2.5-pro", "gemini-2.5-flash"]
    assert any(e.get("type") == "delta" and "stream-rescued" in e.get("text", "") for e in events)


# ---------- fallback client skips SDK retries ----------

def test_fallback_client_disables_sdk_retries(monkeypatch):
    _env(monkeypatch)
    llm._clients.pop("gemini", None)
    c = llm.client_for("gemini")
    assert c.max_retries == 0


# ---------- free image stand-in while xAI images are unfunded ----------

def test_image_pollinations_returns_ready_url(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "pollinations")
    url = asyncio.run(llm.generate_image("a red panda coding on a laptop"))
    assert url is not None and url.startswith("https://image.pollinations.ai/prompt/")
    assert "a%20red%20panda" in url and "model=flux" in url and "nologo=true" in url


def test_image_pollinations_off_by_default(monkeypatch):
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.IMAGE_FALLBACK_PROVIDER == ""


def test_image_falls_back_to_pollinations_when_primary_errors(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "pollinations")
    monkeypatch.setattr(settings, "XAI_API_KEY", "xk")

    class _Images:
        async def generate(self, **kwargs):
            raise RuntimeError("xAI image credits exhausted")

    class _Client:
        images = _Images()

    monkeypatch.setattr(llm, "client_for", lambda provider: _Client())
    url = asyncio.run(llm.generate_image("a neon robot in accra at night"))
    assert url is not None and url.startswith("https://image.pollinations.ai/prompt/")
    assert "neon%20robot" in url and "model=flux" in url


def test_image_prompt_defaults_to_no_text_visuals(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "pollinations")
    monkeypatch.setattr(settings, "XAI_API_KEY", "")
    url = asyncio.run(llm.generate_image("a cozy puppy sleeping on a cloud"))
    assert "no%20readable%20text" in url and "no%20captions" in url


def test_free_image_cascade_falls_through_to_pollinations(monkeypatch):
    # gemini first but has no key → skipped; pollinations (no key needed) serves.
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "gemini,pollinations")
    monkeypatch.setattr(settings, "XAI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    url = asyncio.run(llm.generate_image("sunrise over labadi beach"))
    assert url is not None and url.startswith("https://image.pollinations.ai/prompt/")


def test_free_image_cascade_order_is_respected(monkeypatch):
    # An earlier working engine wins; pollinations is never consulted.
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "gemini,pollinations")
    monkeypatch.setattr(settings, "XAI_API_KEY", "")

    async def _fake_gemini(_prompt: str) -> str:
        return "data:image/png;base64,AAA="

    monkeypatch.setattr(llm, "_gemini_image", _fake_gemini)
    url = asyncio.run(llm.generate_image("paper planes over osu"))
    assert url == "data:image/png;base64,AAA="


def test_free_image_cascade_skips_unknown_and_failed_engines(monkeypatch):
    monkeypatch.setattr(settings, "IMAGE_FALLBACK_PROVIDER", "madeupengine,huggingface,pollinations")
    monkeypatch.setattr(settings, "XAI_API_KEY", "")

    async def _boom(_prompt: str):
        raise RuntimeError("hf returned 503")

    monkeypatch.setattr(llm, "_hf_image", _boom)
    url = asyncio.run(llm.generate_image("kente pattern study in gold and green"))
    assert url is not None and url.startswith("https://image.pollinations.ai/prompt/")


def test_free_image_keyed_engines_skip_cleanly_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "HF_API_TOKEN", "")
    monkeypatch.setattr(settings, "WORKERS_AI_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "WORKERS_AI_API_TOKEN", "")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "")
    assert asyncio.run(llm._gemini_image("x")) is None
    assert asyncio.run(llm._hf_image("x")) is None
    assert asyncio.run(llm._workers_ai_image("x")) is None


def test_free_image_response_parsers():
    import base64

    gemini_payload = {
        "candidates": [
            {"content": {"parts": [
                {"text": "here you go"},
                {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"PNG").decode()}},
            ]}}
        ]
    }
    assert llm._gemini_image_b64(gemini_payload).startswith("data:image/png;base64,")
    assert llm._gemini_image_b64({"candidates": [{"content": {"parts": [{"text": "no img"}]}}]}) is None

    cf_ok = {"success": True, "result": {"image": base64.b64encode(b"IMG").decode()}}
    assert llm._workers_ai_image_b64(cf_ok).startswith("data:image/png;base64,")
    assert llm._workers_ai_image_b64({"success": True, "result": {}}) is None
    import pytest

    with pytest.raises(ValueError):
        llm._workers_ai_image_b64({"success": False, "errors": [{"message": "quota"}]})
