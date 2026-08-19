"""xAI (Grok) service — OpenAI-compatible chat, vision, live search and image APIs.

Every model name and the base URL are env-configurable, so this same client can be
pointed at any OpenAI-compatible provider (the multi-provider router seam).

All calls are instrumented: mood_llm_requests_total / mood_llm_request_duration_seconds
/ mood_llm_stream_chunks_total (see core/metrics).
"""

import logging
import re
import time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI, RateLimitError

from ..config import settings
from ..core.metrics import LLM_CHUNKS, LLM_COUNT, LLM_LAT

log = logging.getLogger(__name__)


class LLMNotConfigured(Exception):
    pass


def friendly_ai_error(exc: Exception) -> str:
    if isinstance(exc, LLMNotConfigured):
        return "AI provider not configured — set XAI_API_KEY (get one at https://console.x.ai)."
    s = str(exc)
    if "401" in s or "api key" in s.lower() or "authentication" in s.lower():
        return "AI provider authentication failed — check XAI_API_KEY."
    return f"AI request failed: {s[:240]}"


SEARCH_PARAMS: dict[str, Any] = {
    "mode": "auto",  # model decides when to search
    "return_citations": True,
    "sources": [{"type": "web"}, {"type": "x"}, {"type": "news"}],
}

_TEXTY_VISUAL_RE = re.compile(
    r"\b(text|caption|subtitle|subtitles|watermark|logo text|title card|typography|letters|wordmark|signage|"
    r"write\b|written\b|spell\b|words\b|label\b|overlay\b)\b",
    re.IGNORECASE,
)


class LLMService:
    """OpenAI-compatible client with a provider registry + per-task router.

    Providers are env-driven: xai (default), gemini, openai — a provider with no
    API key is skipped by the router (falls back to xai). Claude can be added via
    any OpenAI-compat gateway (e.g. LiteLLM) by pointing OPENAI_BASE_URL at it.
    """

    @staticmethod
    def _visual_no_text_guard(prompt: str) -> str:
        p = (prompt or "").strip()
        if not p:
            return p
        if _TEXTY_VISUAL_RE.search(p):
            return p
        return p + ", no readable text, no captions, no subtitles, no typography, no watermark, no logo overlays"

    @staticmethod
    def _pollinations_image_url(prompt: str) -> str:
        from urllib.parse import quote
        import secrets

        q = quote(prompt[:800])
        seed = secrets.randbelow(10**9)
        return (
            f"{settings.POLLINATIONS_IMAGE_URL}/{q}"
            f"?width=1024&height=1024&seed={seed}&model={settings.POLLINATIONS_MODEL}&nologo=true&enhance=true"
        )

    _clients: dict[str, AsyncOpenAI] = {}

    def _provider_specs(self) -> dict[str, tuple[str, str]]:
        """key → (base_url, api_key)."""
        return {
            "xai": (settings.XAI_BASE_URL, settings.XAI_API_KEY),
            "gemini": (settings.GEMINI_BASE_URL, settings.GEMINI_API_KEY),
            "openai": (settings.OPENAI_BASE_URL, settings.OPENAI_API_KEY),
            "arena": (settings.ARENA_AI_BASE_URL, settings.ARENA_AI_API_KEY),
            "freetheai": (settings.FREETHEAI_BASE_URL, settings.FREETHEAI_API_KEY),
            "extrabrain": (settings.EXTRA_BRAIN_BASE_URL, settings.EXTRA_BRAIN_API_KEY),
        }

    def provider_available(self, key: str) -> bool:
        spec = self._provider_specs().get(key)
        return bool(spec and spec[1])

    def _arena_ready(self) -> bool:
        return bool(settings.ARENA_AI_API_KEY and settings.ARENA_AI_MODEL)

    def _fb_ready(self) -> bool:
        fb = (settings.LLM_FALLBACK_PROVIDER or "").strip()
        return bool(fb and settings.LLM_FALLBACK_MODEL and self.provider_available(fb))

    def _fb_buckets(self, class_fast: bool) -> list[tuple[str, str]]:
        """Stand-in stack buckets, same-class first then sibling (separate quotas)."""
        if not self._fb_ready():
            return []
        fb = (settings.LLM_FALLBACK_PROVIDER or "").strip()
        fast, pro = settings.LLM_FALLBACK_MODEL, (settings.LLM_FALLBACK_MODEL_PRO or settings.LLM_FALLBACK_MODEL)
        return [(fb, fast), (fb, pro)] if class_fast else [(fb, pro), (fb, fast)]

    def _freeai_ready(self) -> bool:
        return bool(settings.FREETHEAI_API_KEY and settings.FREETHEAI_MODEL)

    def _freeai_buckets(self, class_fast: bool) -> list[tuple[str, str]]:
        """FreeTheAi extra-capacity buckets, same-class first, de-duplicated."""
        if not self._freeai_ready():
            return []
        fast, pro = (settings.FREETHEAI_MODEL_FAST or settings.FREETHEAI_MODEL), settings.FREETHEAI_MODEL
        out = [("freetheai", fast), ("freetheai", pro)] if class_fast else [("freetheai", pro), ("freetheai", fast)]
        seen, res = set(), []
        for t in out:
            if t[1] not in seen:
                seen.add(t[1])
                res.append(t)
        return res

    def _extra_ready(self) -> bool:
        return bool(settings.EXTRA_BRAIN_API_KEY and settings.EXTRA_BRAIN_MODEL)

    def _extra_buckets(self, class_fast: bool) -> list[tuple[str, str]]:
        """Generic OpenAI-compatible extra-brain buckets (Groq/Cerebras/Mistral/
        OpenRouter/CF Workers AI), same-class first, de-duplicated."""
        if not self._extra_ready():
            return []
        fast, pro = (settings.EXTRA_BRAIN_MODEL_FAST or settings.EXTRA_BRAIN_MODEL), settings.EXTRA_BRAIN_MODEL
        out = [("extrabrain", fast), ("extrabrain", pro)] if class_fast else [("extrabrain", pro), ("extrabrain", fast)]
        seen, res = set(), []
        for t in out:
            if t[1] not in seen:
                seen.add(t[1])
                res.append(t)
        return res

    def _failover(self, provider: str | None, model: str) -> tuple[str | None, str]:
        """First brain at the seam (any xAI-bound call): 🥇 Arena.ai when set →
        🥈 LLM_FALLBACK_* stand-in stack → 🥉 FreeTheAi extra capacity → xAI itself.
        Class-aware at every tier: picker fast/mini → fast bucket, else pro bucket.
        Unset the envs and the primary xAI stack resumes with zero code changes."""
        if provider not in (None, "xai"):
            return provider, model
        fastish = any(k in model.lower() for k in ("fast", "mini"))
        if self._arena_ready():
            fast_m = settings.ARENA_AI_MODEL_FAST or settings.ARENA_AI_MODEL
            return "arena", (fast_m if fastish else settings.ARENA_AI_MODEL)
        if self._fb_ready():
            fast, pro = settings.LLM_FALLBACK_MODEL, (settings.LLM_FALLBACK_MODEL_PRO or settings.LLM_FALLBACK_MODEL)
            return (settings.LLM_FALLBACK_PROVIDER or "").strip(), (fast if fastish else pro)
        if self._freeai_ready():
            fast_m = settings.FREETHEAI_MODEL_FAST or settings.FREETHEAI_MODEL
            return "freetheai", (fast_m if fastish else settings.FREETHEAI_MODEL)
        if self._extra_ready():
            fast_m = settings.EXTRA_BRAIN_MODEL_FAST or settings.EXTRA_BRAIN_MODEL
            return "extrabrain", (fast_m if fastish else settings.EXTRA_BRAIN_MODEL)
        return provider, model

    def _rescue_chain(self, provider: str | None, model: str) -> list[tuple[str, str]]:
        """Ordered deeper tiers to walk on 429s — class is preserved across
        providers (fast-class requests land on fast-class buckets at every tier).
        Each tier is visited exactly once, instantly (no SDK backoff sleeps)."""
        if provider == "arena":
            class_fast = bool(settings.ARENA_AI_MODEL_FAST) and model == settings.ARENA_AI_MODEL_FAST
            return self._fb_buckets(class_fast) + self._freeai_buckets(class_fast) + self._extra_buckets(class_fast)
        fb = (settings.LLM_FALLBACK_PROVIDER or "").strip()
        if provider and provider == fb:
            class_fast = model == settings.LLM_FALLBACK_MODEL
            chain: list[tuple[str, str]] = []
            if settings.LLM_FALLBACK_429_SWAP:  # sibling bucket swap (kill-switchable)
                other = settings.LLM_FALLBACK_MODEL_PRO if class_fast else settings.LLM_FALLBACK_MODEL
                if other and other != model:
                    chain.append((fb, other))
            return chain + self._freeai_buckets(class_fast) + self._extra_buckets(class_fast)
        if provider == "freetheai":
            class_fast = model == (settings.FREETHEAI_MODEL_FAST or settings.FREETHEAI_MODEL)
            return [t for t in self._freeai_buckets(class_fast) if t[1] != model] + self._extra_buckets(class_fast)
        if provider == "extrabrain":
            class_fast = model == (settings.EXTRA_BRAIN_MODEL_FAST or settings.EXTRA_BRAIN_MODEL)
            return [t for t in self._extra_buckets(class_fast) if t[1] != model]
        return []

    async def _call_with_chain(self, provider: str | None, model: str, call):
        """Try (provider, model); on 429s walk _rescue_chain top-down until some
        tier answers — the full brain cascade Arena → Gemini buckets → FreeTheAi.
        Every tier is tried at most once; the last 429 surfaces to the route."""
        tiers = [(provider, model), *self._rescue_chain(provider, model)]
        for i, tgt in enumerate(tiers):
            try:
                return await call(*tgt)
            except RateLimitError:
                if i == len(tiers) - 1:
                    raise
                log.warning("429 on %s/%s → cascading to %s/%s", tgt[0], tgt[1], tiers[i + 1][0], tiers[i + 1][1])
        raise RateLimitError  # pragma: no cover — unreachable

    def client_for(self, provider: str | None) -> AsyncOpenAI:
        key = provider or "xai"
        if key not in self._clients:
            base_url, api_key = self._provider_specs()[key]
            if not api_key:
                raise LLMNotConfigured(f"Provider '{key}' has no API key set.")
            # The stand-in stack + Arena seam reject 429s immediately (max_retries=0):
            # _rescue_chain then recovers in ~0s instead of the SDK sleeping through
            # server-guided retryDelays (measured: a naive retry = 29.5s for "Hello").
            no_retry = key in {"arena", "freetheai", "extrabrain", (settings.LLM_FALLBACK_PROVIDER or "").strip()}
            self._clients[key] = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=0 if no_retry else 2)
        return self._clients[key]

    @property
    def client(self) -> AsyncOpenAI:
        return self.client_for("xai")

    def route(self, task: str) -> tuple[str, str]:
        """task (chat|coding|agents|deepsearch) → (provider, model).

        Routing away from xAI requires BOTH: the provider's API key set AND a
        ROUTE_MODEL_<TASK> override — otherwise it deterministically falls back
        to xAI. Safe against half-configured envs."""
        t = task.upper()
        if t == "FAST":
            return "xai", settings.MODEL_FAST
        want = (getattr(settings, f"PROVIDER_{t}", "xai") or "xai").lower()
        override = (getattr(settings, f"ROUTE_MODEL_{t}", "") or "").strip()
        if want != "xai" and override and self.provider_available(want):
            return want, override
        return "xai", settings.MODEL_CHAT

    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        enable_search: bool = False,
        provider: str | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        provider, model = self._failover(provider, model)
        LLM_COUNT.labels(model=model, kind="stream").inc()
        t0 = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {}
            if enable_search and provider in (None, "xai"):  # Live Search is an xAI feature
                kwargs["extra_body"] = {"search_parameters": SEARCH_PARAMS}
            if think and provider in (None, "xai") and "mini" in model:
                # only the mini family takes an explicit effort knob; grok-4 reasons by default
                kwargs.setdefault("extra_body", {})["reasoning_effort"] = "high"
            stream = await self._call_with_chain(
                provider,
                model,
                lambda p, m: self.client_for(p).chat.completions.create(
                    model=m,
                    messages=messages,
                    stream=True,
                    temperature=0.7,
                    stream_options={"include_usage": True},  # final chunk carries token usage
                    **kwargs,
                ),
            )
            usage: dict = {}
            async for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u:
                    usage = {
                        "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                    }
                citations = getattr(chunk, "citations", None)  # xAI live-search citations
                if citations:
                    yield {"type": "citations", "citations": list(citations)}
                if not chunk.choices:
                    continue
                if think:
                    # 🧠 xAI reasoning models emit live reasoning_content deltas (grok-4 default,
                    # grok-3-mini at high effort) — surfaced as thinking traces by the route.
                    rc = getattr(chunk.choices[0].delta, "reasoning_content", None)
                    if rc:
                        yield {"type": "reasoning", "text": rc}
                text = getattr(chunk.choices[0].delta, "content", None)
                if text:
                    LLM_CHUNKS.labels(model=model).inc()
                    yield {"type": "delta", "text": text}
            if usage:
                yield {"type": "usage", "usage": usage}  # routes meter this; not forwarded to clients
        finally:
            LLM_LAT.labels(model=model, kind="stream").observe(time.perf_counter() - t0)

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        usage_out: dict | None = None,  # pass a dict to receive provider token usage
        provider: str | None = None,
    ) -> str:
        m = model or settings.MODEL_FAST
        provider, m = self._failover(provider, m)
        LLM_COUNT.labels(model=m, kind="complete").inc()
        t0 = time.perf_counter()
        try:
            resp = await self._call_with_chain(
                provider,
                m,
                lambda p, mm: self.client_for(p).chat.completions.create(
                    model=mm,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
            )
            if usage_out is not None:
                u = getattr(resp, "usage", None)
                if u:
                    usage_out["prompt_tokens"] = getattr(u, "prompt_tokens", 0) or 0
                    usage_out["completion_tokens"] = getattr(u, "completion_tokens", 0) or 0
            return resp.choices[0].message.content or ""
        finally:
            LLM_LAT.labels(model=m, kind="complete").observe(time.perf_counter() - t0)

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        provider: str | None = None,
    ) -> Any:
        """One function-calling round. Returns the raw assistant message object
        (inspect .tool_calls; convert with .model_dump(exclude_none=True) to re-append)."""
        m = model or settings.MODEL_CHAT
        provider, m = self._failover(provider, m)
        LLM_COUNT.labels(model=m, kind="complete").inc()
        t0 = time.perf_counter()
        try:
            resp = await self._call_with_chain(
                provider,
                m,
                lambda p, mm: self.client_for(p).chat.completions.create(
                    model=mm, messages=messages, tools=tools, tool_choice="auto", temperature=0.2
                ),
            )
            return resp.choices[0].message
        finally:
            LLM_LAT.labels(model=m, kind="complete").observe(time.perf_counter() - t0)

    async def complete_with_search(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.4,
        usage_out: dict | None = None,
        provider: str | None = None,
    ) -> tuple[str, list[str]]:
        """Non-streaming completion with xAI Live Search. Returns (text, citations).
        Live Search is xAI-only — other providers should use plain complete()."""
        m = model or settings.MODEL_CHAT
        provider, m = self._failover(provider, m)
        LLM_COUNT.labels(model=m, kind="search").inc()
        t0 = time.perf_counter()
        try:
            extra: dict[str, Any] = {}
            if provider in (None, "xai"):
                extra["extra_body"] = {"search_parameters": SEARCH_PARAMS}
            resp = await self._call_with_chain(
                provider,
                m,
                lambda p, mm: self.client_for(p).chat.completions.create(
                    model=mm, messages=messages, temperature=temperature, **extra
                ),
            )
            if usage_out is not None:
                u = getattr(resp, "usage", None)
                if u:
                    usage_out["prompt_tokens"] = getattr(u, "prompt_tokens", 0) or 0
                    usage_out["completion_tokens"] = getattr(u, "completion_tokens", 0) or 0
            citations = getattr(resp, "citations", None) or []
            return (resp.choices[0].message.content or "", list(citations))
        finally:
            LLM_LAT.labels(model=m, kind="search").observe(time.perf_counter() - t0)

    async def generate_image(self, prompt: str, **opts: Any) -> str | None:
        """Generate an image; xAI primary, free engines as an ordered cascade.

        The cascade comes from IMAGE_FALLBACK_PROVIDER — a comma-separated list
        tried left→right (e.g. "gemini,huggingface,pollinations"). Every entry is
        a FREE engine: pollinations needs no key at all; gemini / huggingface /
        cloudflare ride that provider's free daily quota. With no XAI_API_KEY the
        first working entry IS the image engine (fully-free stack). A provider
        without credentials, that errors, or that returns no image is skipped to
        the next; None bubbles up when nothing produced an image.
        """
        prompt = self._visual_no_text_guard(prompt)
        chain = self._image_fallback_chain()
        if settings.XAI_API_KEY:
            m = settings.MODEL_IMAGE
            LLM_COUNT.labels(model=m, kind="image").inc()
            t0 = time.perf_counter()
            try:
                res = await self.client.images.generate(model=m, prompt=prompt, n=1, **opts)
                d = res.data[0]
                if getattr(d, "url", None):
                    return d.url
                b64 = getattr(d, "b64_json", None)
                if b64:
                    return f"data:image/png;base64,{b64}"
                log.warning("primary image provider returned no image — trying free chain %s", chain)
            except Exception:
                log.warning("primary image provider failed — trying free chain %s", chain, exc_info=True)
            finally:
                LLM_LAT.labels(model=m, kind="image").observe(time.perf_counter() - t0)
        for name in chain:
            try:
                out = await self._free_image(name, prompt)
            except Exception:
                log.warning("free image provider %r failed — trying next", name, exc_info=True)
                out = None
            if out:
                return out
        if not chain:
            log.warning(
                "no image engine available — set XAI_API_KEY and/or "
                "IMAGE_FALLBACK_PROVIDER (e.g. 'pollinations' is free, no key)"
            )
        return None

    @staticmethod
    def _image_fallback_chain() -> list[str]:
        """IMAGE_FALLBACK_PROVIDER as a clean, ordered list (single value = chain of one)."""
        raw = settings.IMAGE_FALLBACK_PROVIDER or ""
        return [p.strip().lower() for p in raw.split(",") if p.strip()]

    async def _free_image(self, name: str, prompt: str) -> str | None:
        """One hop of the free-image cascade. Returns a URL or data: URL, or None
        when the engine is not configured (unknown name / missing credentials)."""
        if name == "pollinations":
            LLM_COUNT.labels(model=settings.POLLINATIONS_MODEL, kind="image").inc()
            return self._pollinations_image_url(prompt)
        if name == "gemini":
            out = await self._gemini_image(prompt)
        elif name in ("huggingface", "hf"):
            out = await self._hf_image(prompt)
        elif name in ("cloudflare", "workers-ai"):
            out = await self._workers_ai_image(prompt)
        else:
            log.warning("unknown IMAGE_FALLBACK_PROVIDER entry %r — skipped", name)
            return None
        if out:
            LLM_COUNT.labels(model=f"free:{name}", kind="image").inc()
        return out

    async def _gemini_image(self, prompt: str) -> str | None:
        """Gemini image model via the native generateContent API (free daily quota in AI Studio)."""
        if not settings.GEMINI_API_KEY:
            return None
        import httpx

        url = f"{settings.GEMINI_NATIVE_BASE_URL}/models/{settings.GEMINI_IMAGE_MODEL}:generateContent"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            r = await client.post(url, headers={"x-goog-api-key": settings.GEMINI_API_KEY}, json=body)
            r.raise_for_status()
            return self._gemini_image_b64(r.json())

    @staticmethod
    def _gemini_image_b64(payload: dict[str, Any]) -> str | None:
        """First inline image out of a generateContent response → data: URL."""
        import base64

        for cand in payload.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data") or {}
                data = inline.get("data")
                if data:
                    base64.b64decode(data)  # raises → counts as provider failure
                    mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                    return f"data:{mime};base64,{data}"
        return None

    async def _hf_image(self, prompt: str) -> str | None:
        """Hugging Face Inference — free daily credits on a free token (FLUX-schnell default)."""
        if not settings.HF_API_TOKEN:
            return None
        import base64

        import httpx

        url = f"{settings.HF_IMAGE_BASE_URL}/{settings.HF_IMAGE_MODEL}"
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:  # cold models can take ~20s
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.HF_API_TOKEN}"},
                json={"inputs": prompt},
            )
            r.raise_for_status()
            mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            if not mime.startswith("image/") or not r.content:
                raise ValueError(f"huggingface returned non-image payload ({mime})")
            return f"data:{mime};base64,{base64.b64encode(r.content).decode()}"

    async def _workers_ai_image(self, prompt: str) -> str | None:
        """Cloudflare Workers AI — free 10k neurons/day (FLUX.1-schnell default)."""
        account = settings.WORKERS_AI_ACCOUNT_ID or settings.CLOUDFLARE_ACCOUNT_ID
        token = settings.WORKERS_AI_API_TOKEN or settings.CLOUDFLARE_API_TOKEN
        if not (account and token):
            return None
        import httpx

        url = (
            f"{settings.CLOUDFLARE_API_BASE_URL}/accounts/{account}"
            f"/ai/run/{settings.WORKERS_AI_IMAGE_MODEL}"
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            r = await client.post(url, headers={"Authorization": f"Bearer {token}"}, json={"prompt": prompt})
            r.raise_for_status()
            return self._workers_ai_image_b64(r.json())

    @staticmethod
    def _workers_ai_image_b64(payload: dict[str, Any]) -> str | None:
        """Workers AI text-to-image envelope → data: URL. Raises on API-reported failure."""
        import base64

        if payload.get("success") is False:
            raise ValueError(f"workers ai error: {payload.get('errors')}")
        data = (payload.get("result") or {}).get("image")
        if not data:
            return None
        base64.b64decode(data)  # raises → counts as provider failure
        return f"data:image/png;base64,{data}"


llm = LLMService()
