"""💳 Admin payments — publish MoMo/bank destinations, review money manually.

    GET    /admin/payments/methods            list every destination (incl. retired)
    POST   /admin/payments/methods            publish one
    PATCH  /admin/payments/methods/{id}       edit / retire
    DELETE /admin/payments/methods/{id}       delete (only if unused)

    GET    /admin/payments                    the review queue (filter by status)
    POST   /admin/payments/{id}/approve       verify → grant the plan
    POST   /admin/payments/{id}/reject        decline with a reason
    POST   /admin/payments/grant              grant a plan with NO payment row (comp/refund fix)
    GET    /admin/payments/summary            revenue + queue depth

Approval is the ONLY path that grants a plan, and it is idempotent: approving an
already-approved payment is a no-op rather than a second month.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Payment, PaymentMethod, Subscription, User
from ...db.session import get_db
from ...services import payments as pay
from ..deps import require_admin
from .payments import method_out, payment_out

router = APIRouter()
log = logging.getLogger(__name__)


class MethodCreate(BaseModel):
    kind: str = Field(default="momo", pattern="^(momo|bank|cash|other)$")
    label: str = Field(min_length=2, max_length=80)
    network: str = Field(default="", max_length=20)
    account_name: str = Field(default="", max_length=120)
    account_number: str = Field(default="", max_length=60)
    bank_name: str = Field(default="", max_length=80)
    instructions: str = Field(default="", max_length=1200)
    currency: str = Field(default="", max_length=8)
    active: bool = True
    sort_order: int = Field(default=0, ge=0, le=999)


class MethodUpdate(BaseModel):
    """PATCH semantics: absent/None → unchanged."""

    kind: str | None = Field(default=None, pattern="^(momo|bank|cash|other)$")
    label: str | None = Field(default=None, min_length=2, max_length=80)
    network: str | None = Field(default=None, max_length=20)
    account_name: str | None = Field(default=None, max_length=120)
    account_number: str | None = Field(default=None, max_length=60)
    bank_name: str | None = Field(default=None, max_length=80)
    instructions: str | None = Field(default=None, max_length=1200)
    currency: str | None = Field(default=None, max_length=8)
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class ReviewRequest(BaseModel):
    admin_note: str = Field(default="", max_length=600)


class GrantRequest(BaseModel):
    """Grant a plan with no money attached — comps, refund corrections, testing."""

    user_id: str = Field(min_length=8, max_length=36)
    plan: str = Field(default="pro", pattern="^(free|pro)$")
    months: int = Field(default=1, ge=1, le=36)
    admin_note: str = Field(default="", max_length=600)


# ───────────────────────────────────────────────── payment methods

@router.get("/methods")
async def list_methods(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (
        await db.execute(
            select(PaymentMethod).order_by(PaymentMethod.sort_order, PaymentMethod.created_at)
        )
    ).scalars().all()
    return {
        "methods": [method_out(m) for m in rows],
        "networks": list(pay.MOMO_NETWORKS),
        "kinds": list(pay.METHOD_KINDS),
        "currency": (settings.CURRENCY or "GHS").upper(),
        "providers": pay.providers(),
    }


@router.post("/methods", status_code=201)
async def create_method(
    req: MethodCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    if req.kind == "momo" and not req.account_number.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A mobile money method needs the number users should send to.",
        )
    row = PaymentMethod(
        kind=req.kind,
        label=req.label.strip(),
        network=req.network.strip().lower(),
        account_name=req.account_name.strip(),
        account_number=req.account_number.strip(),
        bank_name=req.bank_name.strip(),
        instructions=req.instructions.strip(),
        currency=(req.currency or settings.CURRENCY or "GHS").upper(),
        active=req.active,
        sort_order=req.sort_order,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)  # created_at/updated_at are server-side
    return method_out(row)


@router.patch("/methods/{mid}")
async def update_method(
    mid: str, req: MethodUpdate, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    row = await db.get(PaymentMethod, mid)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment method not found")
    for field in ("kind", "label", "network", "account_name", "account_number",
                  "bank_name", "instructions", "active", "sort_order"):
        val = getattr(req, field)
        if val is not None:
            setattr(row, field, val.strip() if isinstance(val, str) else val)
    if req.currency is not None:
        row.currency = (req.currency or settings.CURRENCY or "GHS").upper()
    await db.commit()
    await db.refresh(row)
    return method_out(row)


@router.delete("/methods/{mid}", status_code=204)
async def delete_method(
    mid: str, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    """Delete a destination. Refuses if payments reference it — retire instead,
    so historical records keep pointing at something real."""
    row = await db.get(PaymentMethod, mid)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment method not found")
    used = int(
        (await db.scalar(select(func.count(Payment.id)).where(Payment.method_id == mid))) or 0
    )
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{used} payment(s) reference this method — set it inactive instead of deleting.",
        )
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


# ─────────────────────────────────────────────────── review queue

@router.get("")
async def list_payments(
    status_filter: str = Query(default="pending", alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = select(Payment)
    if status_filter and status_filter != "all":
        q = q.where(Payment.status == status_filter)
    rows = (await db.execute(q.order_by(Payment.created_at.desc()).limit(limit))).scalars().all()

    # Attach the payer's email — an admin matching a MoMo alert needs it.
    emails: dict[str, str] = {}
    for uid in {p.user_id for p in rows}:
        u = await db.get(User, uid)
        if u:
            emails[uid] = u.email
    return {
        "payments": [
            {**payment_out(p), "user_email": emails.get(p.user_id, ""), "user_id": p.user_id}
            for p in rows
        ],
        "pending_count": int(
            (await db.scalar(select(func.count(Payment.id)).where(Payment.status == "pending"))) or 0
        ),
    }


async def _activate(db: AsyncSession, user: User, plan: str, months: int) -> datetime:
    """Grant `plan` for `months`, extending any period the user already has."""
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    if not sub:
        sub = Subscription(user_id=user.id)
        db.add(sub)
        await db.flush()
    sub.current_period_end = pay.extend_period(sub.current_period_end, months)
    sub.status = "active"
    user.plan = plan
    return sub.current_period_end


@router.post("/{pid}/approve")
async def approve_payment(
    pid: str, req: ReviewRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    """Verify money received → activate the plan. Idempotent."""
    row = await db.get(Payment, pid)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if row.status == "approved":
        # A double-clicked Approve must not hand out two months.
        return {**payment_out(row), "already": True}
    if row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Payment is {row.status} — only pending payments can be approved."
        )

    user = await db.get(User, row.user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payer account no longer exists")

    period_end = await _activate(db, user, row.plan, row.months)
    row.status = "approved"
    row.admin_note = req.admin_note.strip()
    row.reviewed_by = admin.id
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    try:
        from ...services.notify import push_later

        push_later(
            user.id,
            "payment_approved",
            f"🎉 {row.plan.title()} is active",
            f"Payment confirmed — your plan runs to {period_end.date().isoformat()}.",
            {"screen": "/settings"},
        )
    except Exception as e:
        log.info("approval notify skipped: %s", e)

    return {
        **payment_out(row),
        "user_email": user.email,
        "plan": user.plan,
        "current_period_end": period_end.isoformat(),
    }


@router.post("/{pid}/reject")
async def reject_payment(
    pid: str, req: ReviewRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    row = await db.get(Payment, pid)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    if row.status == "rejected":
        return {**payment_out(row), "already": True}
    if row.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Payment is {row.status} — only pending payments can be rejected."
        )
    row.status = "rejected"
    row.admin_note = req.admin_note.strip()
    row.reviewed_by = admin.id
    row.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)

    try:
        from ...services.notify import push_later

        push_later(
            row.user_id,
            "payment_rejected",
            "Payment could not be confirmed",
            (req.admin_note.strip() or "We couldn't match that transaction. Please check the reference.")[:140],
            {"screen": "/settings"},
        )
    except Exception as e:
        log.info("rejection notify skipped: %s", e)
    return payment_out(row)


@router.post("/grant")
async def grant_plan(
    req: GrantRequest, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)
):
    """Grant (or revoke) a plan directly — comps, refunds, support fixes.

    Records an `approved` payment of amount 0 so the audit trail still explains
    why the account changed. Granting `free` ends the paid period immediately.
    """
    user = await db.get(User, req.user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if req.plan == "free":
        user.plan = "free"
        sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id))
        if sub:
            sub.status = "canceled"
            sub.current_period_end = None
        period_end = None
    else:
        period_end = await _activate(db, user, req.plan, req.months)

    row = Payment(
        user_id=user.id,
        provider="manual",
        invoice_code=pay.new_invoice_code(),
        reference=f"ADMIN-GRANT-{admin.email[:20]}",
        amount_minor=0,
        currency=(settings.CURRENCY or "GHS").upper(),
        plan=req.plan,
        months=req.months,
        offer_id="admin_grant",
        status="approved",
        admin_note=req.admin_note.strip() or "Granted by admin (no payment collected)",
        reviewed_by=admin.id,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    return {
        "user_id": user.id,
        "email": user.email,
        "plan": user.plan,
        "current_period_end": period_end.isoformat() if period_end else None,
    }


@router.get("/summary")
async def payments_summary(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Queue depth + collected revenue, for the owner dashboard."""
    async def count(*where) -> int:
        return int((await db.scalar(select(func.count(Payment.id)).where(*where))) or 0)

    approved_total = int(
        (
            await db.scalar(
                select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
                    Payment.status == "approved"
                )
            )
        )
        or 0
    )
    currency = (settings.CURRENCY or "GHS").upper()
    return {
        "pending": await count(Payment.status == "pending"),
        "approved": await count(Payment.status == "approved"),
        "rejected": await count(Payment.status == "rejected"),
        "collected_minor": approved_total,
        "collected_label": pay.format_money(approved_total, currency),
        "currency": currency,
        "providers": pay.providers(),
        "offers": [o.as_dict() for o in pay.plan_offers()],
    }
