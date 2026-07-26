import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def uid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    is_admin: Mapped[bool] = mapped_column(default=False)  # app-owner panel access (ADMIN_EMAILS env also grants)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PlatformSetting(Base):
    """Key/value platform knobs owned by the app admin (app access gate, etc.)."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")  # owner | member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )  # set → shared with all workspace members
    project_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )  # 🗂 filed under a Project (instructions + pinned files apply). No FK: projects
    # is created by a later migration, and a plain column keeps create_all order-free.
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # rolling cross-chat recall summary
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )  # author of user messages (team chats); null = legacy / assistant
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class FileAsset(Base):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(120))
    path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="inactive")
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageEvent(Base):
    """One metered API action (chat reply, agent run, image, …) for plan dashboards/limits."""

    __tablename__ = "usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # chat | agent | deepsearch | voice | image | task | api
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    estimated: Mapped[bool] = mapped_column(default=False)  # True → token counts are heuristic, not provider-reported
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SharedLink(Base):
    """Public read-only link to a conversation (revocable)."""

    __tablename__ = "shared_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PluginConnection(Base):
    """Per-user OAuth connection to an external app (Gmail, Calendar, GitHub)."""

    __tablename__ = "plugin_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))  # gmail | google_calendar | github
    account: Mapped[str | None] = mapped_column(String(255), nullable=True)  # email / login label
    access_token_enc: Mapped[str] = mapped_column(Text)  # Fernet-encrypted
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[str] = mapped_column(String(500), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PendingAction(Base):
    """A write tool call (send email, create event/issue) awaiting in-chat user approval."""

    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tool: Mapped[str] = mapped_column(String(60))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Domain(Base):
    """Custom domain: connected (BYO, DNS-verified) or purchased in-app via registrar."""

    __tablename__ = "domains"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="connected")  # connected | purchased
    status: Mapped[str] = mapped_column(String(20), default="pending_dns")  # pending_dns | active | failed | purchasing
    verification_token: Mapped[str] = mapped_column(String(64), default="")
    registrar: Mapped[str | None] = mapped_column(String(24), nullable=True)  # godaddy | external
    registrar_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(default=True)
    years: Mapped[int] = mapped_column(Integer, default=1)
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    brand_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # white-label name
    contact: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # registrant contact (purchased)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # registrar expiry (synced)
    accent: Mapped[str | None] = mapped_column(String(9), nullable=True)  # white-label accent hex, e.g. #7c9bff
    logo_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # small data-URL logo (white-label)
    # ⚔️ white-label arena (per-domain debates on the domain owner's branding)
    arena_enabled: Mapped[bool] = mapped_column(default=False)
    arena_daily_cap: Mapped[int] = mapped_column(Integer, default=0)  # 0 = fall back to the user's plan cap
    arena_brand: Mapped[str | None] = mapped_column(String(80), nullable=True)  # shown as the arena/judge name
    arena_judge: Mapped[str | None] = mapped_column(String(60), nullable=True)  # judge model id (xAI-routed)
    arena_panel: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{"provider","model","label"}] custom panel
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkspaceInvite(Base):
    """Shareable join link for a workspace (optionally gated to a bound domain's email addresses)."""

    __tablename__ = "workspace_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    """FCM push tokens — Phase 1 push notifications (see docs/PUSH-NOTIFICATIONS.md)."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    platform: Mapped[str] = mapped_column(String(16), default="android")  # android | ios | web
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Film(Base):
    """🎬 Storyboard films — async-rendered multi-scene movies (docs/VIDEO-SOUND.md).

    status: rendering → done | failed. progress tracks finished scene renders.
    filename points into MEDIA_DIR (24h TTL janitor); scenes_json keeps the
    shot/narration pairs (and lets users re-mix the film later)."""

    __tablename__ = "films"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    scenes_json: Mapped[str] = mapped_column(Text, default="[]")     # [{shot, narration}]
    status: Mapped[str] = mapped_column(String(16), default="rendering", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)        # scenes rendered
    scene_count: Mapped[int] = mapped_column(Integer, default=0)
    scene_seconds: Mapped[int] = mapped_column(Integer, default=6)
    aspect: Mapped[str] = mapped_column(String(8), default="16:9")
    quality: Mapped[str] = mapped_column(String(8), default="720p")
    style: Mapped[str] = mapped_column(String(40), default="cinematic")
    audio: Mapped[str] = mapped_column(String(20), default="none")   # none|voice|voice+ambience
    voice_id: Mapped[str] = mapped_column(String(20), default="alloy")
    music: Mapped[str] = mapped_column(String(12), default="soft")
    tempo: Mapped[float] = mapped_column(Float, default=1.0)
    subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    filename: Mapped[str] = mapped_column(String(40), default="")
    poster: Mapped[str] = mapped_column(String(44), default="")        # <uuid>_p.jpg hero frame
    views: Mapped[int] = mapped_column(Integer, default=0)             # 👁 public share-page opens
    brand_name: Mapped[str] = mapped_column(String(80), default="")    # ⭐ brand woven in (v1.0.0)
    fallback_url: Mapped[str] = mapped_column(String(600), default="")
    script: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Design(Base):
    """🎨 Design Studio — flyers, logos & banners with print-tier PNGs.

    `file` = web-tier PNG in MEDIA_DIR (<uuid>_d.png), `print_file` = 300-DPI
    lanczos-upscaled print tier (<uuid>_dp.png). `prompt` keeps the compiled
    art-director prompt so users can re-mix the design later."""

    __tablename__ = "designs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="flyer", index=True)   # flyer|logo|banner
    idea: Mapped[str] = mapped_column(Text, default="")             # user's raw idea
    brief: Mapped[str] = mapped_column(Text, default="")            # art-director rewrite (if enhanced)
    prompt: Mapped[str] = mapped_column(Text, default="")           # compiled provider prompt
    style: Mapped[str] = mapped_column(String(24), default="minimal")
    palette: Mapped[str] = mapped_column(String(16), default="auto")
    transparent: Mapped[bool] = mapped_column(Boolean, default=False)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    file: Mapped[str] = mapped_column(String(44), default="")       # web tier png
    print_file: Mapped[str] = mapped_column(String(44), default="")  # 300-DPI print png
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BrandKit(Base):
    """🧑‍💼 One-per-user brand identity — woven into Design Studio generations.

    logo_design_id points at a Design row (kind=logo) whose web-tier PNG is
    composited onto flyers/banners post-render (designer._overlay_brand_logo)."""

    __tablename__ = "brand_kits"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    brand_name: Mapped[str] = mapped_column(String(120), default="")
    tagline: Mapped[str] = mapped_column(String(200), default="")
    color_primary: Mapped[str] = mapped_column(String(9), default="")     # #rrggbb
    color_secondary: Mapped[str] = mapped_column(String(9), default="")
    color_accent: Mapped[str] = mapped_column(String(9), default="")
    font_vibe: Mapped[str] = mapped_column(String(16), default="modern")  # classic|modern|bold
    logo_design_id: Mapped[str] = mapped_column(String(36), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Edit(Base):
    """✂️ Auto video edits — upload + instruction → staged ffmpeg pipeline.

    src_name is the uploaded clip in MEDIA_DIR (kept until the row is deleted);
    out_name is <uuid>_e.mp4 (public hex URL, swept by the 24h janitor)."""

    __tablename__ = "edits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    instruction: Mapped[str] = mapped_column(Text, default="")
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="rendering", index=True)  # rendering|done|failed
    src_name: Mapped[str] = mapped_column(String(48), default="")
    out_name: Mapped[str] = mapped_column(String(44), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DesignOrder(Base):
    """🛍 Client mode — a magic link customers use to order a design.

    /order/<token> is public (unguessable token); each submission stages a ✋
    design_create action on the OWNER's account. Approving renders the design
    and flips the order to delivered; the customer picks it up via the same link."""

    __tablename__ = "design_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(12), default="open")      # open|staged|delivered|closed
    customer_name: Mapped[str] = mapped_column(String(80), default="")
    idea: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(12), default="flyer")
    style: Mapped[str] = mapped_column(String(24), default="minimal")
    design_id: Mapped[str] = mapped_column(String(36), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Reel(Base):
    """📺 Creator Reel — the shared public feed of creator videos.

    A post is either an UPLOAD (creator's own clip, stored under `filename`
    in MEDIA_DIR) or a SHARE of something Mood already generated (a Film or an
    in-chat video), in which case `source_url` points at the existing media and
    no bytes are copied.

    Reel posts are keepsakes: unlike muxed films they use the `_r.mp4` suffix
    so the 24h media janitor never sweeps them out from under the feed. Rows
    are visible to every signed-in user while `status == "live"`; the author
    can unpost (status="hidden") or delete outright.
    """

    __tablename__ = "reels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    author_name: Mapped[str] = mapped_column(String(80), default="")   # denormalized for the feed
    caption: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(12), default="upload")  # upload|film|chat|duet|repost
    film_id: Mapped[str] = mapped_column(String(36), default="")       # set when shared from a film
    filename: Mapped[str] = mapped_column(String(48), default="")      # <uuid>_r.mp4 in MEDIA_DIR
    source_url: Mapped[str] = mapped_column(String(600), default="")   # shared (already-hosted) media
    poster: Mapped[str] = mapped_column(String(48), default="")        # <uuid>_rp.jpg cover frame
    # 🎬 Studio lineage — a duet/repost credits the reel it came from, so the
    # feed can show "duet with @x" and the original author keeps attribution.
    parent_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    parent_author: Mapped[str] = mapped_column(String(80), default="")
    effect: Mapped[str] = mapped_column(String(16), default="")         # key into reel_studio.EFFECTS
    captioned: Mapped[bool] = mapped_column(Boolean, default=False)     # captions burned in
    status: Mapped[str] = mapped_column(String(12), default="live", index=True)  # live|hidden
    # Denormalized engagement counters — the feed reads them straight off the
    # row instead of running three COUNT(*)s per card. `likes` and `saves` are
    # reconcilable from their join tables; `views`/`shares` are pure tallies.
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    saves: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    # Python-side default (microseconds) in ADDITION to the server default:
    # SQLite's CURRENT_TIMESTAMP only has 1-second resolution, so two posts in
    # the same second would tie and the paginated feed could skip or repeat
    # rows. Feed queries still add `id` as a deterministic tiebreak.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )


class ReelLike(Base):
    """❤️ One row per (reel, user) — the unique PK makes liking idempotent."""

    __tablename__ = "reel_likes"

    reel_id: Mapped[str] = mapped_column(ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReelSave(Base):
    """🔖 Saved/bookmarked reels — one row per (reel, user), same idempotent
    composite PK as likes. Powers the viewer's private "Saved" tab, which is
    why it carries its own timestamp: saves are listed newest-saved-first, not
    in the order the reels were posted."""

    __tablename__ = "reel_saves"

    reel_id: Mapped[str] = mapped_column(ForeignKey("reels.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class Project(Base):
    """🗂 Project — a durable container for related chats, files and instructions.

    Grok/ChatGPT-style Projects: a persistent workspace with its OWN system
    instructions and its OWN document set, so every chat inside it starts with
    the same brief and can retrieve from the same library. Conversations point
    here via Conversation.project_id (nullable → the chat is loose/unfiled).
    """

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )  # set → the whole project is visible to the team
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    instructions: Mapped[str] = mapped_column(Text, default="")  # prepended to every chat in the project
    emoji: Mapped[str] = mapped_column(String(8), default="🗂")
    accent: Mapped[str | None] = mapped_column(String(9), nullable=True)  # #rrggbb card tint
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProjectFile(Base):
    """📎 A file pinned to a project (the project's own knowledge base).

    The upload itself stays a normal FileAsset — this is only the membership
    edge, so the same file can be pinned to several projects and unpinning
    never destroys the user's upload.
    """

    __tablename__ = "project_files"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduledTask(Base):
    """⏰ Scheduled task — a saved prompt Mood runs on a schedule, unattended.

    Grok Tasks parity: "every weekday at 07:00, brief me on AI news". The
    scheduler (services/scheduler.py) claims due tasks atomically, runs the
    prompt through the chosen mode (chat / deepsearch / agent), appends the
    result to a dedicated conversation and pushes a notification.

    Scheduling is intentionally cron-free: kind + hour/minute + weekday mask is
    enough for the product, trivially explainable in the UI, and computable
    without a cron parser dependency.
    """

    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )  # results are appended here, so a task reads as one growing thread
    title: Mapped[str] = mapped_column(String(160))
    prompt: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16), default="chat")  # chat | deepsearch | agent
    search: Mapped[bool] = mapped_column(default=True)  # ground the run in live web results
    schedule_kind: Mapped[str] = mapped_column(String(12), default="daily")  # once | hourly | daily | weekly
    hour_utc: Mapped[int] = mapped_column(Integer, default=8)     # 0-23, UTC
    minute_utc: Mapped[int] = mapped_column(Integer, default=0)   # 0-59, UTC
    weekdays: Mapped[str] = mapped_column(String(20), default="")  # "0,1,2,3,4" (Mon=0); "" = every day
    enabled: Mapped[bool] = mapped_column(default=True)
    notify: Mapped[bool] = mapped_column(default=True)  # push when the run finishes
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")  # ok | failed | running
    last_error: Mapped[str] = mapped_column(Text, default="")
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskRun(Base):
    """📜 One execution of a ScheduledTask — the audit trail behind the Tasks page."""

    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("scheduled_tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | failed
    summary: Mapped[str] = mapped_column(Text, default="")  # first ~600 chars of the answer
    error: Mapped[str] = mapped_column(Text, default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ApiKey(Base):
    """🔑 Developer API key — programmatic access to the same Grok-class brain.

    Only a SHA-256 hash is stored; the plaintext `mk_live_…` secret is shown
    once at creation and can never be recovered. `prefix` is the first 11
    characters, kept in the clear purely so the UI can label rows ("mk_live_a1b…")
    without weakening the secret.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="API key")
    prefix: Mapped[str] = mapped_column(String(16), index=True)  # display label, e.g. mk_live_a1b
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # sha256 hex of the secret
    scopes: Mapped[str] = mapped_column(String(200), default="chat")  # csv: chat,search,images
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
