import os

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _asyncpg_url(cls, v):
        """Hosting platforms hand out postgres(ql):// DSNs — force the asyncpg driver,
        and translate libpq-style query params that asyncpg can't parse.

        Neon/Aiven/Supabase URIs often carry `?sslmode=require&channel_binding=require`;
        asyncpg only understands `ssl=…`, so pasted-as-is URIs would crash at boot.
        """
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = "postgresql+asyncpg://" + v[len("postgres://"):]
            elif v.startswith("postgresql://"):
                v = "postgresql+asyncpg://" + v[len("postgresql://"):]
            if "+asyncpg://" in v and "?" in v:
                base, _, qs = v.partition("?")
                keep: list[str] = []
                for pair in qs.split("&"):
                    k, _, val = pair.partition("=")
                    if k == "sslmode":
                        if val in ("require", "verify-ca", "verify-full"):
                            keep.append("ssl=require")
                        # disable/prefer/allow → asyncpg's default negotiation is fine; drop
                    elif k == "channel_binding":
                        continue  # asyncpg negotiates channel binding itself
                    else:
                        keep.append(pair)
                v = base + (("?" + "&".join(keep)) if keep else "")
        return v

    # Core
    APP_NAME: str = "ChatMood"
    DEBUG: bool = False
    DATABASE_URL: str = "postgresql+asyncpg://mood:mood@localhost:5432/mood"
    REDIS_URL: str = "redis://localhost:6379/0"
    QDRANT_URL: str = "http://localhost:6333"
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    UPLOAD_DIR: str = "./storage"       # auto-relocated to /tmp on serverless (see _serverless_relocate)
    MOOD_SERVERLESS: str = ""           # force "1" to emulate a serverless host locally
    MAX_UPLOAD_MB: int = 25
    MAX_AUDIO_UPLOAD_MB: int = 15  # music / spoken-word uploads for AI analysis
    MAX_VIDEO_UPLOAD_MB: int = 50  # mp4/mov uploads for scene-by-scene AI analysis
    VIDEO_ANALYSIS_FRAMES: int = 6  # frames sampled per video for vision captioning
    MAX_FILE_CHARS: int = 30_000
    CORS_ORIGINS: str = "http://localhost:3000"
    FRONTEND_URL: str = "http://localhost:3000"

    # xAI / Grok (OpenAI-compatible API)
    XAI_API_KEY: str = ""
    XAI_BASE_URL: str = "https://api.x.ai/v1"
    MODEL_CHAT: str = "grok-4"
    MODEL_FAST: str = "grok-3-mini"
    MODEL_VISION: str = "grok-2-vision-1212"
    MODEL_IMAGE: str = "grok-2-image-1212"
    MODEL_CHAT_FAST: str = "grok-4-fast"      # ⚡ premium picker fast tier
    MODEL_CODE: str = "grok-code-fast-1"      # 💻 premium picker coding tier
    THINK_TRACE_KEEP: int = 120               # 🧠 max reasoning deltas persisted per message

    # ⚔️ Arena (Pro feature) — panel models per provider
    ARENA_XAI_MODEL: str = ""          # default: MODEL_CHAT (grok-4) — also the judge
    ARENA_OPENAI_MODEL: str = "gpt-4o"
    ARENA_GEMINI_MODEL: str = "gemini-2.5-pro"
    ARENA_CODE_MODEL: str = "grok-code-fast-1"

    # LLM failover — while set, calls that would go to xAI (chat, picker tiers,
    # vision analysis, titles, memory) are answered by the stand-in provider
    # instead. Perfect for "xAI credits not purchased yet" or provider outages.
    # Unset both and the Grok primary stack resumes instantly.
    # 🥇 Arena.ai first-brain seam (dormant until Arena.ai opens its developer API).
    # Set key + model and Arena pre-empts every xAI-bound call; 429s cascade down
    # to the LLM_FALLBACK_* stand-in stack automatically. All off by default.
    ARENA_AI_API_KEY: str = ""
    ARENA_AI_BASE_URL: str = "https://api.arena.ai/v1"  # placeholder — no public endpoint exists yet
    ARENA_AI_MODEL: str = ""                             # flagship brain id; REQUIRED for the seam to engage
    ARENA_AI_MODEL_FAST: str = ""                        # optional fast tier; falls back to ARENA_AI_MODEL
    # 🥈 FreeTheAi extra-brain seam (freetheai.xyz) — OpenAI-compatible free gateway.
    # Dormant until FREETHEAI_API_KEY + FREETHEAI_MODEL are set; then it joins the
    # brain cascade (after the LLM_FALLBACK_* stack) as always-on extra capacity.
    # NOTE: free keys need a daily /checkin in their Discord — if it lapses, the
    # gateway 401s and the cascade simply falls through to the next tier.
    FREETHEAI_API_KEY: str = ""
    FREETHEAI_BASE_URL: str = "https://api.freetheai.xyz/v1"
    FREETHEAI_MODEL: str = ""        # flagship-class alias, e.g. "opc/deepseek-v4-flash-free"
    FREETHEAI_MODEL_FAST: str = ""   # optional fast tier; falls back to FREETHEAI_MODEL
    # 🧬 Generic extra-brain seam — ANY OpenAI-compatible free tier joins the rescue
    # cascade with ZERO code changes: Groq (console.groq.com → instant key), Cerebras,
    # Mistral La Plateforme, OpenRouter (":free" models), or Cloudflare Workers AI
    # (base https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1). Dormant until
    # EXTRA_BRAIN_API_KEY + EXTRA_BRAIN_MODEL are set.
    EXTRA_BRAIN_API_KEY: str = ""
    EXTRA_BRAIN_BASE_URL: str = "https://api.groq.com/openai/v1"
    EXTRA_BRAIN_MODEL: str = ""        # flagship-class, e.g. "llama-3.3-70b-versatile"
    EXTRA_BRAIN_MODEL_FAST: str = ""   # optional fast tier; falls back to EXTRA_BRAIN_MODEL
    LLM_FALLBACK_PROVIDER: str = ""   # e.g. "gemini" (needs that provider's API key set)
    LLM_FALLBACK_MODEL: str = ""      # fast-tier fallback model, e.g. "gemini-2.5-flash" (picker fast/mini tiers land here)
    LLM_FALLBACK_MODEL_PRO: str = "gemini-2.5-pro"  # flagship-class fallback model (default chat/coding/deep-search land here)
    LLM_FALLBACK_429_SWAP: bool = True  # on a rate-limit, retry once instantly on the sibling bucket (flash↔pro = separate quotas)
    CONTEXT_BUDGET_S: float = 4.0       # hard per-source time budget for memory/recall/doc retrieval (vector store may be unreachable — never stall first-token)
    CONTEXT_BREAKER_S: float = 300.0    # after a context source fails, skip it instantly for this long (circuit breaker)
    # 🧠 Vector store backend — "auto": pgvector inside the Postgres you already own
    # (zero extra infra); a real external Qdrant (QDRANT_URL ≠ localhost) wins when set.
    VECTOR_BACKEND: str = "auto"        # auto | pgvector | qdrant
    EMBED_PROVIDER: str = "auto"        # auto | gemini | fastembed | openai — auto prefers Gemini (free, no 90MB ONNX download)
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"  # dims pinned to EMBED_VECTOR_SIZE (table stays consistent)
    GEMINI_EMBED_API_KEY: str = ""      # optional SECOND Google key (separate daily quota) for embeddings
    # Any OpenAI-compatible embeddings endpoint as the middle rescue tier (before local
    # ONNX) — e.g. Cloudflare Workers AI @cf/baai/bge-small-en-v1.5 (384-dim, free).
    # Falls back to OPENAI_API_KEY / OPENAI_BASE_URL when unset.
    EMBED_API_KEY: str = ""
    EMBED_API_BASE_URL: str = ""
    QUOTA_ECONOMY: bool = False         # True = pause fact-extraction + title prettifier (daily-budget shield for tiny keys)

    # Durable file storage — local disk by default; Cloudflare R2 (S3-compatible,
    # zero egress fees) when the R2_* envs are set. DB rows that hold files keep a
    # local abs path OR an "r2:<key>" marker, so both backends coexist safely.
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = "chatmood"
    R2_PRESIGN_SECONDS: int = 3600      # download link TTL for private objects
    R2_PUBLIC_BASE_URL: str = ""        # optional public bucket/CDN base for permanent links
    R2_ENDPOINT_URL: str = ""           # override for ANY S3-compatible service (MinIO/B2/moto)

    # Multi-provider router (any OpenAI-compatible endpoint; inactive until keys set)
    GEMINI_API_KEY: str = ""
    GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    # Route heavy tasks per provider: xai | gemini | openai (falls back to xai if unconfigured)
    PROVIDER_CHAT: str = "xai"
    PROVIDER_CODING: str = "xai"
    PROVIDER_AGENTS: str = "xai"
    PROVIDER_DEEPSEARCH: str = "xai"
    # Optional model overrides when routing away from xAI
    ROUTE_MODEL_CODING: str = ""      # e.g. gemini-2.5-pro | gpt-4o
    ROUTE_MODEL_AGENTS: str = ""
    ROUTE_MODEL_DEEPSEARCH: str = ""
    # 🖼️ Free image engines, tried left→right when xAI image gen fails or is unfunded.
    # Comma-separated cascade: "pollinations" or e.g. "gemini,huggingface,pollinations".
    # With no xAI key configured, the FIRST entry becomes the primary image engine.
    # All four are free: pollinations needs NO key at all; the others ride the
    # provider's free daily quota on a free key you (or the operator) already have.
    IMAGE_FALLBACK_PROVIDER: str = ""
    POLLINATIONS_IMAGE_URL: str = "https://image.pollinations.ai/prompt"
    POLLINATIONS_MODEL: str = "flux"
    # "gemini" — Gemini image models via the native generateContent API (NOT the
    # OpenAI-compat base). AI Studio free tier carries a daily image quota; reuses
    # GEMINI_API_KEY. Quota-0 keys simply 429 → the cascade moves on.
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"
    GEMINI_NATIVE_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
    # "huggingface" (alias "hf") — HF Inference free daily credits on a free token.
    HF_API_TOKEN: str = ""
    HF_IMAGE_MODEL: str = "black-forest-labs/FLUX.1-schnell"
    HF_IMAGE_BASE_URL: str = "https://router.huggingface.co/hf-inference/models"
    # "cloudflare" (alias "workers-ai") — Workers AI free tier (10k neurons/day ≈
    # hundreds of FLUX-schnell images). Dedicated pair wins; unset → falls back to
    # the generic CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN used for DNS/Stream.
    WORKERS_AI_ACCOUNT_ID: str = ""
    WORKERS_AI_API_TOKEN: str = ""
    WORKERS_AI_IMAGE_MODEL: str = "@cf/black-forest-labs/flux-1-schnell"
    # 🖼️ Generated images: archive a durable copy to object storage (R2/local) + file it
    # in the user's library, instead of relying on provider hotlinks that can go stale.
    IMAGE_PERSIST: bool = True
    IMAGE_PERSIST_TTL_S: int = 604_800  # render-link TTL — SigV4 presign max = 7 days
    ROUTE_MODEL_CHAT: str = ""

    # Web search: "xai_live" (built in) or "tavily"
    SEARCH_PROVIDER: str = "xai_live"
    TAVILY_API_KEY: str = ""

    # Voice: Whisper STT + TTS (OpenAI-compatible; swap provider to taste)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    WHISPER_MODEL: str = "whisper-1"
    TTS_MODEL: str = "tts-1"
    TTS_VOICE: str = "alloy"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID: str = ""

    # Custom domains (connect own + real-time purchase for business white-label)
    PLATFORM_CNAME_TARGET: str = ""   # e.g. cname.chatmood.app — users CNAME their domain here
    PLATFORM_A_RECORD_IP: str = ""    # apex IP for purchased domains (optional; www gets CNAME)
    DOMAIN_MARKUP_PCT: int = 20       # your margin on registrar cost price
    GODADDY_API_KEY: str = ""         # registrar integration (developer.godaddy.com/keys)
    GODADDY_API_SECRET: str = ""
    GODADDY_ENV: str = "ote"          # "ote" = sandbox testing · "production" = real purchases
    VERCEL_API_TOKEN: str = ""        # optional: auto-attach verified domains to your Vercel project
    VERCEL_PROJECT_ID: str = ""
    VERCEL_TEAM_ID: str = ""
    # Optional: one-tap DNS setup for BYO domains already hosted on Cloudflare.
    # The token needs Zone:Read + DNS:Edit on the relevant zones.
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_API_BASE_URL: str = "https://api.cloudflare.com/client/v4"
    BASE_DOMAIN: str = ""             # platform's own host (skipped in per-domain analytics)
    DOMAIN_SYNC_HOURS: int = 24       # how often the watchdog refreshes registrar expiry dates
    DOMAIN_RENEW_WINDOW_DAYS: int = 30  # show "Renew now" / send reminder inside this window
    INVITE_TTL_DAYS: int = 7          # workspace invite link lifetime

    # Clerk federation (Phase 1 — optional; docs/CLERK-AUTH-ASSESSMENT.md)
    # Verifies Clerk session JWTs (RS256 JWKS), links by email, mints our JWT.
    # Disabled until CLERK_ISSUER is set. Zero schema changes.
    CLERK_ISSUER: str = ""            # e.g. https://your-app.clerk.accounts.dev
    CLERK_SECRET_KEY: str = ""        # sk_live_/sk_test_… — for /v1/users profile lookups
    CLERK_AUDIENCE: str = ""          # optional azp/aud restriction
    CLERK_JWKS_URL: str = ""          # override; default {CLERK_ISSUER}/.well-known/jwks.json

    # App owner / admin panel
    ADMIN_EMAILS: str = ""            # comma-separated owner emails (always admin, in addition to users.is_admin)
    ADMIN_BOOTSTRAP_EMAIL: str = ""   # env-defined owner account (created/promoted at boot)
    ADMIN_BOOTSTRAP_PASSWORD: str = ""  # owner-only password for the bootstrap account
    APP_PASSWORD: str = ""            # optional sign-up access code seeded into the platform gate

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()}

    # Memory / RAG
    MEMORY_COLLECTION: str = "user_memories"
    EMBED_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"  # local fastembed (skipped when not installed)
    EMBED_API_MODEL: str = "text-embedding-3-small"  # fallback over OPENAI_BASE_URL when fastembed absent
    EMBED_VECTOR_SIZE: int = 384
    MEMORY_TOP_K: int = 6

    # Cross-conversation recall (remembering previous chats)
    RECALL_TOP_K: int = 3           # semantically relevant past chats injected per message
    RECALL_MIN_SCORE: float = 0.38  # cosine threshold for past-chat recall
    RECENT_CHATS_DIGEST: int = 2    # most-recent chat summaries injected into brand-new conversations

    # Plugins (Gmail / Google Calendar / GitHub via OAuth)
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"  # OAuth callbacks point here
    PLUGIN_TOKEN_KEY: str = ""      # Fernet key; falls back to one derived from JWT_SECRET (dev)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    PLUGIN_MAX_CALLS: int = 4       # tool-call rounds per message

    # Push notifications (Phase 1: FCM HTTP v1 — docs/PUSH-NOTIFICATIONS.md)
    FCM_PROJECT_ID: str = ""
    FCM_SERVICE_ACCOUNT_JSON: str = ""  # entire service-account JSON as one env string
    NOTIFY_COOLDOWN_SECONDS: int = 300  # per user+kind, process-local

    # Video generation — comma-chain of providers, first that succeeds wins:
    #   "reel"        = zero-key ChatMood Reel (FLUX scene stills → ffmpeg Ken Burns mp4)
    #   "pollinations"= gen.pollinations.ai video models (needs POLLINATIONS_API_KEY)
    #   "xai"         = Grok video when credits exist
    # Default ships "reel" so chat video works TODAY with no keys; "xai,reel" once funded.
    VIDEO_PROVIDER: str = "reel"
    MODEL_VIDEO: str = "grok-video-1"
    POLLINATIONS_API_KEY: str = ""
    POLLINATIONS_VIDEO_URL: str = "https://gen.pollinations.ai/video"
    POLLINATIONS_VIDEO_MODEL: str = "wan-fast"
    VIDEO_MAX_WAIT_SECONDS: int = 240
    # 🎬 ChatMood Reel composer (ffmpeg present in both deploy images — verified)
    REEL_ENABLED: bool = True
    REEL_MAX_SCENES: int = 5
    # 🎞️ v1.9.8 richer reels: LLM storyboard (free Groq brain, fail-open to
    # deterministic beats) + AI voiceover (TTS cascade: Groq Orpheus → Cloudflare
    # aura-1 (same WorkersAI token as embeddings) → unofficial gTTS → silent).
    REEL_STORYBOARD: bool = True
    REEL_NARRATION: bool = True
    GROQ_TTS_MODEL: str = "canopylabs/orpheus-v1-english"
    GROQ_TTS_VOICE: str = "tara"
    TTS_TIMEOUT_S: int = 45

    # 🎨🎬 In-chat creation (v1.9.7): type "create an image of…" / "make a video of…"
    # in any chat and ChatMood generates inline. Zero-cost heuristic router (no LLM spent).
    CHAT_MEDIA: bool = True
    CHAT_IMAGE_RATE_PER_MIN: int = 8
    CHAT_VIDEO_RATE_PER_MIN: int = 2
    # Cinema Sound: AI voiceover + ambience muxed onto generated video (ffmpeg)
    FFMPEG_PATH: str = "ffmpeg"
    MEDIA_DIR: str = "/tmp/mood-media"      # muxed videos served from /media/files/{name}
    MEDIA_TTL_HOURS: int = 24               # janitor purges muxed files older than this
    # 📺 Reel Studio: extra font dir for libass caption burn-in. Serverless
    # images ship no system fonts, so point this at the bundled family when the
    # host has none (the app's own DejaVu lives in app/assets/fonts).
    REEL_FONTS_DIR: str = ""
    VIDEO_MAX_DOWNLOAD_MB: int = 256        # cap when pulling the provider clip for muxing
    VIDEO_MAX_CASCADE_ATTEMPTS: int = 3     # provider cascade retries (reel → pollinations → xai)

    # Code execution sandbox (built-in run_python_code tool)
    SANDBOX_ENABLED: bool = True    # NOT a hardened security boundary — see services/sandbox.py
    SANDBOX_TIMEOUT: int = 8        # seconds
    SANDBOX_MAX_OUTPUT: int = 6000  # chars captured from stdout/stderr each

    # 🏷 Output watermarking — free tier is badged; paid plans and admins are not.
    # The entitlement rule lives in services/watermark.should_watermark().
    WATERMARK_ENABLED: bool = True
    WATERMARK_TEXT: str = ""        # blank → "Made with {APP_NAME}"
    WATERMARK_TIMEOUT_S: int = 90   # cap on the stamping encode; on timeout the clean render ships

    # 🔴 Live streaming (Reel → Go Live). This repo does NOT host video infra;
    # pick a managed provider and set its keys. Blank → Go Live reports itself
    # unavailable rather than handing creators a dead Start button.
    LIVE_PROVIDER: str = ""              # mux | cloudflare | livekit
    LIVE_MAX_MINUTES: int = 120          # auto-end runaway broadcasts (bills by the minute)
    MUX_TOKEN_ID: str = ""
    MUX_TOKEN_SECRET: str = ""
    CLOUDFLARE_STREAM_TOKEN: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    LIVEKIT_URL: str = ""

    # 💳 Payments — manual mobile money now, gateways when their keys land.
    # Manual needs NO keys: admin publishes a MoMo number, the user submits a
    # transaction reference, an admin approves, the plan activates.
    CURRENCY: str = "GHS"
    PRO_PRICE_MONTHLY_MINOR: int = 15_000   # 150.00 GHS in pesewas (integer minor units)
    PRO_YEAR_MONTHS: int = 10               # yearly = 10× monthly → 2 months free
    MANUAL_PAYMENTS_ENABLED: bool = True
    PAYMENT_EXPIRY_SWEEP_HOURS: float = 6.0  # how often lapsed manual plans are downgraded
    # Gateways — leave blank until you have the keys; the UI shows them as
    # "coming soon" rather than pretending the option doesn't exist.
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    FLUTTERWAVE_SECRET_KEY: str = ""
    FLUTTERWAVE_PUBLIC_KEY: str = ""

    # 🗂 Projects — durable chat/file containers with standing instructions
    PROJECTS_ENABLED: bool = True
    PROJECT_MAX_FILES: int = 40        # pinned documents per project
    PROJECT_MAX_PER_USER: int = 100
    GPT_MAX_PER_USER: int = 40         # user-built Custom GPTs (catalog is unlimited)

    # ⏰ Scheduled tasks — saved prompts ChatMood runs unattended
    TASKS_ENABLED: bool = True
    SCHEDULER_ENABLED: bool = True     # false on extra replicas if you ever want a single runner
    SCHEDULER_TICK_S: float = 60.0     # how often the loop looks for due tasks
    SCHEDULER_BATCH: int = 10          # max tasks claimed per tick
    SCHEDULER_RUN_TIMEOUT_S: int = 300  # hard cap on one unattended run
    TASK_MAX_PER_USER_FREE: int = 3
    TASK_MAX_PER_USER_PRO: int = 30
    TASK_RUNS_KEEP: int = 50           # audit rows retained per task

    # 🔑 Developer API — programmatic access with `mk_live_…` keys
    PUBLIC_API_ENABLED: bool = True
    API_KEY_MAX_PER_USER: int = 10
    API_KEY_RATE_PER_MIN: int = 60     # per-key request budget (plan multiplier applies)

    # Limits
    CHAT_RATE_LIMIT_PER_MIN: int = 30
    HISTORY_WINDOW: int = 20

    # Ops
    AUTO_CREATE_TABLES: bool = True  # dev convenience; prod: false + `alembic upgrade head`
    # 💓 DB keep-warm — serverless Postgres (Neon) idles to sleep and the next request
    # pays a 4-15s wake (measured live). A SELECT 1 every few minutes from the always-on
    # Fly machines keeps the shared endpoint hot for BOTH hosts. False = allow idling.
    DB_KEEP_WARM: bool = True
    DB_KEEP_WARM_S: float = 240.0
    # 🚦 Readiness contract — which dependencies may fail the /readyz probe.
    # Postgres is the only hard requirement: without it every request 500s. Redis
    # and the vector store are OPTIONAL by design — the rate limiter fails open
    # (api/deps.py) and memory/RAG degrade gracefully (services/memory.py), so the
    # app serves chat correctly without either. Fly runs exactly that way today:
    # no REDIS_URL secret, so REDIS_URL is the localhost default and nothing is
    # listening. Treating that as "not ready" would fail the health check on a
    # perfectly healthy machine and break every deploy.
    # Set to "postgres,redis,qdrant" on stacks (docker-compose, Render) that do
    # provision all three and want a stricter gate.
    READINESS_REQUIRED: str = "postgres"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""  # e.g. http://jaeger:4318 to enable tracing

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def readiness_required_set(self) -> set[str]:
        """Dependency names whose failure makes /readyz return 503."""
        return {p.strip().lower() for p in self.READINESS_REQUIRED.split(",") if p.strip()}

    @property
    def serverless(self) -> bool:
        """True when running on an ephemeral host (Vercel / AWS Lambda / forced via MOOD_SERVERLESS=1)."""
        return bool(
            self.MOOD_SERVERLESS == "1"
            or os.environ.get("VERCEL") == "1"
            or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        )

    @model_validator(mode="after")
    def _serverless_relocate(self):
        """Serverless filesystems are read-only except /tmp — move writable dirs there."""
        if self.serverless:
            if self.UPLOAD_DIR.rstrip("/") in ("./storage", "storage", ""):
                self.UPLOAD_DIR = "/tmp/mood-uploads"
            if not self.MEDIA_DIR.startswith("/tmp"):
                self.MEDIA_DIR = "/tmp/mood-media"
        return self


settings = Settings()
