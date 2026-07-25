"""Admin analytics aggregation — engagement, studio mix, sound attach,
film vanity (top films + music mood), device activity."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Design, Device, Film, UsageEvent, User


def _days_series(start_date) -> list[str]:
    return [(start_date + timedelta(days=i)).date().isoformat() for i in range(14)]


async def engagement_analytics(db: AsyncSession, cutoff_days: int = 30) -> dict:
    """Core analytics payload used by /admin/engagement."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)

    # Push funnel
    rows = await db.execute(
        select(UsageEvent.kind, func.count(UsageEvent.id)).where(
            UsageEvent.created_at >= cutoff,
            UsageEvent.kind.like("push%"),
        ).group_by(UsageEvent.kind)
    )
    attempts: dict[str, int] = {}
    delivered: dict[str, int] = {}
    pruned = 0
    for kind, n in rows.all():
        if kind.startswith("push_attempt:"):
            key = kind.split(":", 1)[1]
            attempts[key] = attempts.get(key, 0) + int(n)
        elif kind == "push_prune":
            pruned += int(n)
        elif kind.startswith("push:"):
            key = kind.split(":", 1)[1]
            delivered[key] = delivered.get(key, 0) + int(n)
    kinds = sorted(set(attempts) | set(delivered))
    total_attempts = sum(attempts.values())
    total_delivered = sum(delivered.values())

    # Sound attach rate
    videos_30d = int(
        (await db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.created_at >= cutoff, UsageEvent.kind == "video"))) or 0
    )
    sound_30d = int(
        (await db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.created_at >= cutoff, UsageEvent.kind == "media_sound"))) or 0
    )

    # Studio mix
    studio_rows = await db.execute(
        select(UsageEvent.kind, func.count(UsageEvent.id)).where(
            UsageEvent.created_at >= cutoff,
            UsageEvent.kind.in_(["video", "i2v", "design", "edit", "design_export", "film"]),
        ).group_by(UsageEvent.kind)
    )
    studio_mix = {k: int(n) for k, n in studio_rows.all()}
    COSTS = {"video": 0.12, "i2v": 0.12, "design": 0.04, "edit": 0.05, "film": 0.12, "design_export": 0.0}
    studio_cost = round(sum(n * COSTS.get(k, 0) for k, n in studio_mix.items()), 2)

    # Design kind mix
    dk_rows = await db.execute(
        select(Design.kind, func.count(Design.id)).where(Design.created_at >= cutoff).group_by(Design.kind)
    )
    design_kinds = {k: int(n) for k, n in dk_rows.all()}

    # Top films + music mood mix (30d)
    top_films_rows = (
        await db.execute(
            select(Film).where(Film.views > 0).order_by(Film.views.desc(), Film.created_at.desc()).limit(5)
        )
    ).scalars().all()
    music_rows = await db.execute(
        select(Film.music, func.count(Film.id))
        .where(Film.created_at >= cutoff, Film.status == "done", Film.audio == "voice+ambience")
        .group_by(Film.music)
    )

    # Device activity
    devs = await db.execute(
        select(Device, User.email)
        .join(User, User.id == Device.user_id)
        .order_by(Device.created_at.desc())
        .limit(15)
    )
    activity = []
    for d, email_addr in devs.all():
        events_30d = int(
            (await db.scalar(
                select(func.count(UsageEvent.id)).where(
                    UsageEvent.user_id == d.user_id,
                    UsageEvent.created_at >= cutoff,
                    ~UsageEvent.kind.like("push%"),
                )
            )) or 0
        )
        last_event = await db.scalar(
            select(func.max(UsageEvent.created_at)).where(UsageEvent.user_id == d.user_id)
        )
        activity.append({
            "email": email_addr,
            "platform": d.platform,
            "registered": d.created_at.isoformat() if d.created_at else None,
            "last_seen": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "events_30d": events_30d,
            "last_event": last_event.isoformat() if last_event else None,
        })

    return {
        "push": {
            "by_kind": [
                {"kind": k, "attempts": attempts.get(k, 0), "delivered": delivered.get(k, 0)}
                for k in kinds
            ],
            "attempts_30d": total_attempts,
            "delivered_30d": total_delivered,
            "tokens_pruned_30d": pruned,
            "delivery_rate": round(total_delivered / total_attempts, 3) if total_attempts else None,
        },
        "studio_mix": studio_mix,
        "studio_cost_usd": studio_cost,
        "design_kinds": design_kinds,
        "sound": {
            "videos_30d": videos_30d,
            "with_sound_30d": sound_30d,
            "attach_rate": round(min(sound_30d, videos_30d) / videos_30d, 3) if videos_30d else None,
        },
        "top_films": [
            {
                "id": f.id,
                "title": (f.prompt or "").strip()[:70],
                "views": f.views,
                "scenes": f.scene_count,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in top_films_rows
        ],
        "music_mix": {m: int(n) for m, n in music_rows},
        "device_activity": activity,
    }
