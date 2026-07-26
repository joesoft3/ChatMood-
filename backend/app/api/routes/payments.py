"""💳 Payments API (user side) — pay by mobile money, get upgraded.

    GET  /payments/options          plans, published MoMo/bank destinations, providers
    POST /payments/submit           "I paid" → a pending payment for admin review
    GET  /payments/mine             this user's payment history + current status

The manual flow needs no API keys at all, which is why it ships first:

    admin publishes a MoMo number → user pays on their phone → user submits the
    transaction reference → admin verifies → plan activates

Paystack/Flutterwave/Stripe write the same `Payment` row once their keys exist,
so nothing downstream (admin queue, history, plan grant) has to change.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.models import Payment, PaymentMethod, Subscription, User
from ...db.session import get_db
from ...services import payments as pay
from ..deps import enforce_rate_limit, get_current_user

router = APIRouter()
log = logging.getLogger(__name__)


class PaymentSubmit(BaseModel):
    offer_id: str = Field(min_length=2, max_length=32)
    method_id: str | None = None                       # which destination they paid to
    reference: str = Field(min_length=3, max_length=64)  # MoMo/bank transaction id
    payer_name: str = Field(default="", max_length=120)
    payer_phone: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=600)


def method_out(m: PaymentMethod) -> dict:
    return {
        "id": m.id,
        "kind": m.kind,
        "label": m.label,
        "network": m.network,
        "account_name": m.account_name,
        "account_number": m.account_number,
        "bank_name": m.bank_name,
        "instructions": m.instructions,
        "currency": m.currency,
        "active": bool(m.active),
        "sort_order": m.sort_order,
    }


def payment_out(p: Payment) -> dict:
    return {
        "id": p.id,
        "provider": p.provider,
        "invoice_code": p.invoice_code,
        "reference": p.reference,
        "amount_minor": p.amount_minor,
        "amount_label": pay.format_money(p.amount_minor, p.currency),
        "currency": p.currency,
        "plan": p.plan,
        "months": p.months,
        "offer_id": p.offer_id,
        "status": p.status,
        "note": p.note,
        "admin_note": p.admin_note,
        "payer_name": p.payer_name,
        "payer_phone": p.payer_phone,
        "method_id": p.method_id,
        "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/options")
async def payment_options(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Everything the upgrade screen needs: prices, where to pay, what's pending."""
    methods = (
        await db.execute(
            select(PaymentMethod)
            .where(PaymentMethod.active.is_(True))
            .order_by(PaymentMethod.sort_order, PaymentMethod.created_at)
        )
    ).scalars().all()

    pending = (
        await db.execute(
            select(Payment)
            .where(Payment.user_id == user.id, Payment.status == "pending")
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    return {
        "plan": user.plan,
        "currency": (settings.CURRENCY or "GHS").upper(),
        "offers": [o.as_dict() for o in pay.plan_offers()],
        "methods": [method_out(m) for m in methods],
        "providers": pay.providers(),
        "default_provider": pay.default_provider(),
        "manual_enabled": bool(settings.MANUAL_PAYMENTS_ENABLED),
        "pending": payment_out(pending) if pending else None,
        "current_period_end": (
            sub.current_period_end.isoformat() if sub and sub.current_period_end else None
        ),
    }


@router.post("/submit", status_code=201)
async def submit_payment(
    req: PaymentSubmit, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Declare a completed manual payment. Creates a PENDING row — never grants a plan.

    Only an admin approval activates a plan; this endpoint deliberately cannot,
    or anyone could self-upgrade by posting a made-up reference.
    """
    if not settings.MANUAL_PAYMENTS_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Manual payments are disabled on this deployment.",
        )
    # Cheap abuse guard: submitting references is free, so cap the rate.
    await enforce_rate_limit(f"pay-submit:{user.id}", 6)

    offer = pay.offer_by_id(req.offer_id)
    if not offer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown plan option")

    method = None
    if req.method_id:
        method = await db.get(PaymentMethod, req.method_id)
        if not method or not method.active:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That payment method is not available")

    reference = pay.clean_reference(req.reference)
    if len(reference) < 3:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Enter the transaction ID from your mobile money confirmation SMS.",
        )

    # One open request at a time — otherwise an impatient user files five and an
    # admin approves the same payment repeatedly.
    existing = (
        await db.execute(
            select(Payment).where(Payment.user_id == user.id, Payment.status == "pending").limit(1)
        )
    ).scalars().first()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You already have a payment awaiting review — we'll email you once it's confirmed.",
        )

    # A reference identifies exactly one real transaction. Re-use is either a
    # typo or an attempt to claim someone else's payment; both deserve a stop.
    clash = (
        await db.execute(
            select(Payment).where(
                Payment.reference == reference, Payment.status.in_(("pending", "approved"))
            ).limit(1)
        )
    ).scalars().first()
    if clash:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That transaction ID has already been submitted. Check the reference and try again.",
        )

    row = Payment(
        user_id=user.id,
        method_id=method.id if method else None,
        provider="manual",
        invoice_code=pay.new_invoice_code(),
        reference=reference,
        payer_name=req.payer_name.strip(),
        payer_phone=req.payer_phone.strip(),
        amount_minor=offer.amount_minor,
        currency=offer.currency,
        plan=offer.plan,
        months=offer.months,
        offer_id=offer.id,
        status="pending",
        note=req.note.strip(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    # Tell the owner there's something to review (best-effort — never blocks).
    try:
        from ...services.notify import push_later

        for admin_id in await _admin_ids(db):
            push_later(
                admin_id,
                "payment_pending",
                "💳 Payment awaiting review",
                f"{user.email} · {pay.format_money(row.amount_minor, row.currency)}",
                {"screen": "/admin", "payment_id": row.id},
            )
    except Exception as e:
        log.info("payment notify skipped: %s", e)

    return payment_out(row)


async def _admin_ids(db: AsyncSession) -> list[str]:
    """Admin user ids (DB flag or an ADMIN_EMAILS entry)."""
    rows = (await db.execute(select(User))).scalars().all()
    from ..deps import is_effective_admin

    return [u.id for u in rows if is_effective_admin(u)]


@router.get("/mine")
async def my_payments(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Payment)
            .where(Payment.user_id == user.id)
            .order_by(Payment.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    sub = await db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    return {
        "plan": user.plan,
        "subscription": sub.status if sub else "none",
        "current_period_end": (
            sub.current_period_end.isoformat() if sub and sub.current_period_end else None
        ),
        "payments": [payment_out(p) for p in rows],
    }
