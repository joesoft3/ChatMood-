"""🔑 Public developer API — the same Grok-class brain, over `mk_live_…` keys.

Mounted at /api/v1/public. Authentication is API-key only (see deps.get_api_caller);
session JWTs are deliberately not accepted.

    GET  /public/models              what this deployment can serve
    POST /public/chat/completions    OpenAI-compatible chat (stream: true supported)
    POST /public/search              grounded answer + citations
    POST /public/images              image generation
    GET  /public/usage               the calling key's owner's meters

**Why OpenAI-compatible?** Because it means every existing SDK — `openai-python`,
Vercel AI SDK, LangChain, curl snippets people already have — works by changing
two strings (base_url + api_key). A bespoke schema would be strictly more work
for us and strictly less useful to them.

Every call is metered through the same UsageEvent pipeline as the web app, so
plan limits and the usage dashboard cover programmatic traffic automatically.
"""

import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...core.metrics import track_stream
from ...db.models import ApiKey, User
from ...db.session import get_db
from ...services.llm import friendly_ai_error, llm
from ...services.metering import (
    PLAN_LIMITS,
    count_today,
    estimate_tokens,
    plan_rate_mult,
    record_usage,
    usage_summary,
)
from ..deps import enforce_rate_limit, get_api_caller, require_scope

router = APIRouter()
log = logging.getLogger(__name__)

# Public aliases → the models this deployment actually routes to. Callers pick a
# stable name; we keep the freedom to re-point it (or fail it over) underneath.
PUBLIC_MODELS: dict[str, str] = {
    "mood-flagship": settings.MODEL_CHAT,
    "mood-fast": settings.MODEL_CHAT_FAST,
    "mood-mini": settings.MODEL_FAST,
    "mood-code": settings.MODEL_CODE,
}
DEFAULT_PUBLIC_MODEL = "mood-flagship"


class PublicMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(max_length=100_000)


class ChatCompletionRequest(BaseModel):
    model: str = DEFAULT_PUBLIC_MODEL
    messages: list[PublicMessage] = Field(min_length=1, max_length=100)
    stream: bool = False
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    search: bool = False  # ChatMood extension: ground this completion in live web results


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4_000)
    model: str = DEFAULT_PUBLIC_MODEL


class ImageRequestPublic(BaseModel):
    prompt: str = Field(min_length=2, max_length=4_000)


def resolve_model(name: str | None) -> str:
    """Public alias → concrete model. Unknown aliases fall back to the flagship
    rather than erroring: an integration shouldn't break because it pinned a name
    we later retired."""
    return PUBLIC_MODELS.get((name or "").strip(), PUBLIC_MODELS[DEFAULT_PUBLIC_MODEL])


async def _guard(db: AsyncSession, user: User, key: ApiKey, scope: str) -> None:
    """Scope + rate limit + monthly token plan cap, in that order."""
    require_scope(key, scope)
    await enforce_rate_limit(f"apikey:{key.id}", settings.API_KEY_RATE_PER_MIN * plan_rate_mult(user.plan))
    limits = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])
    if scope == "images":
        cap = limits.get("images_month", 0)
        if cap and await count_today(db, user.id, "image") >= cap:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Image quota reached for the {user.plan} plan ({cap}/month).",
            )


def _completion_envelope(model: str, content: str, usage: dict) -> dict:
    """The OpenAI `chat.completion` shape, so stock SDKs parse it unmodified."""
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


@router.get("/models")
async def list_models(caller: tuple[User, ApiKey] = Depends(get_api_caller)):
    """The catalogue, in OpenAI `list` shape."""
    _, key = caller
    return {
        "object": "list",
        "data": [
            {"id": alias, "object": "model", "owned_by": "chatmood", "backing": backing}
            for alias, backing in PUBLIC_MODELS.items()
        ],
        "scopes": [s for s in (key.scopes or "").split(",") if s],
    }


@router.post("/chat/completions")
async def chat_completions(
    req: ChatCompletionRequest,
    db: AsyncSession = Depends(get_db),
    caller: tuple[User, ApiKey] = Depends(get_api_caller),
):
    user, key = caller
    await _guard(db, user, key, "chat")
    model = resolve_model(req.model)
    messages = [m.model_dump() for m in req.messages]
    live_search = bool(req.search) and settings.SEARCH_PROVIDER == "xai_live"
    if live_search:
        require_scope(key, "search")

    if not req.stream:
        usage: dict = {}
        try:
            if live_search:
                content, citations = await llm.complete_with_search(
                    messages, model=model, temperature=req.temperature, usage_out=usage
                )
                if citations:
                    uniq = list(dict.fromkeys(citations))
                    content += "\n\n**Sources**\n" + "\n".join(
                        f"- [{i + 1}]({u})" for i, u in enumerate(uniq)
                    )
            else:
                content = await llm.complete(
                    messages,
                    model=model,
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    usage_out=usage,
                )
        except Exception as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, friendly_ai_error(e))

        counts = (
            {
                "tokens_in": int(usage.get("prompt_tokens", 0)),
                "tokens_out": int(usage.get("completion_tokens", 0)),
                "estimated": False,
            }
            if usage
            else estimate_tokens(json.dumps(messages), content)
        )
        await record_usage(user.id, "api", model=model, **counts)
        return _completion_envelope(req.model, content, usage)

    # Streaming: OpenAI `chat.completion.chunk` frames terminated by [DONE],
    # which is exactly what stock SDK stream parsers expect.
    async def event_source():
        cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
        created = int(time.time())
        collected: list[str] = []
        usage: dict = {}

        def frame(delta: dict, finish: str | None = None) -> str:
            payload = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return f"data: {json.dumps(payload)}\n\n"

        try:
            yield frame({"role": "assistant", "content": ""})
            async for ev in llm.stream_chat(messages, model=model, enable_search=live_search):
                if ev["type"] == "usage":
                    usage = ev.get("usage") or {}
                    continue
                if ev["type"] == "delta":
                    collected.append(ev["text"])
                    yield frame({"content": ev["text"]})
            yield frame({}, finish="stop")
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': {'message': friendly_ai_error(e), 'type': 'upstream_error'}})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            text = "".join(collected)
            counts = (
                {
                    "tokens_in": int(usage.get("prompt_tokens", 0)),
                    "tokens_out": int(usage.get("completion_tokens", 0)),
                    "estimated": False,
                }
                if usage
                else estimate_tokens(json.dumps(messages), text)
            )
            await record_usage(user.id, "api", model=model, **counts)

    return StreamingResponse(
        track_stream(event_source()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/search")
async def public_search(
    req: SearchRequest,
    db: AsyncSession = Depends(get_db),
    caller: tuple[User, ApiKey] = Depends(get_api_caller),
):
    """A grounded answer with its citations returned as structured data."""
    user, key = caller
    await _guard(db, user, key, "search")
    usage: dict = {}
    try:
        text, citations = await llm.complete_with_search(
            [{"role": "user", "content": req.query}], model=resolve_model(req.model), usage_out=usage
        )
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, friendly_ai_error(e))
    counts = (
        {
            "tokens_in": int(usage.get("prompt_tokens", 0)),
            "tokens_out": int(usage.get("completion_tokens", 0)),
            "estimated": False,
        }
        if usage
        else estimate_tokens(req.query, text)
    )
    await record_usage(user.id, "api", model=resolve_model(req.model), **counts)
    return {"query": req.query, "answer": text, "citations": list(dict.fromkeys(citations))}


@router.post("/images")
async def public_images(
    req: ImageRequestPublic,
    db: AsyncSession = Depends(get_db),
    caller: tuple[User, ApiKey] = Depends(get_api_caller),
):
    user, key = caller
    await _guard(db, user, key, "images")
    try:
        url = await llm.generate_image(req.prompt)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, friendly_ai_error(e))
    if not url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Image generation is not configured on this deployment")
    await record_usage(user.id, "image", model=settings.MODEL_IMAGE)
    return {"created": int(time.time()), "data": [{"url": url}]}


@router.get("/usage")
async def public_usage(
    db: AsyncSession = Depends(get_db),
    caller: tuple[User, ApiKey] = Depends(get_api_caller),
):
    """Meters for the account behind this key — lets integrations self-throttle."""
    user, key = caller
    summary = await usage_summary(db, user.id, user.plan)
    return {**summary, "key": {"name": key.name, "prefix": key.prefix, "calls": key.calls or 0}}
