"""💳 Payments — manual mobile money today, card gateways when keys land.

Ghana-first by design. Stripe is card-only and awkward for the local market, so
the flow that works *right now* is:

    admin publishes a MoMo number  →  user pays from their phone  →  user submits
    the transaction reference  →  admin verifies and approves  →  plan activates

That whole loop needs **zero API keys**, which is why it's the default channel.
Paystack and Flutterwave (both of which do settle Ghanaian MoMo) slot into the
same `Payment` row the moment their keys are configured — see `providers()`.

Design notes worth knowing before changing this:

* **Money is integer minor units** (pesewas), never floats. `12.50 GHS` is
  `1250`. Every conversion goes through `to_minor` / `format_money`.
* **Approval is the only thing that grants a plan**, and it is idempotent — a
  double-clicked Approve must not hand out two months.
* **Periods extend, they don't reset.** Paying early adds to the remaining
  balance instead of throwing it away.
* Provider modules are *declared* here even before their keys exist, so the UI
  can show "coming soon" honestly rather than pretending the option is missing.
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..config import settings

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────── money

def to_minor(amount: float | int | str) -> int:
    """"12.50" → 1250 pesewas. Rejects nonsense rather than silently zeroing."""
    try:
        value = round(float(amount) * 100)
    except (TypeError, ValueError):
        raise ValueError(f"not a valid amount: {amount!r}")
    if value < 0:
        raise ValueError("amount cannot be negative")
    return int(value)


def format_money(minor: int, currency: str = "") -> str:
    """1250 → '12.50 GHS' (currency omitted when blank)."""
    cur = (currency or settings.CURRENCY or "").upper()
    body = f"{minor / 100:,.2f}"
    return f"{body} {cur}".strip()


# ─────────────────────────────────────────────────────── plan catalog

@dataclass(frozen=True)
class PlanOffer:
    id: str            # billing cycle id
    plan: str          # the plan granted on approval
    label: str
    months: int
    amount_minor: int
    currency: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "plan": self.plan,
            "label": self.label,
            "months": self.months,
            "amount_minor": self.amount_minor,
            "amount": round(self.amount_minor / 100, 2),
            "currency": self.currency,
            "price_label": format_money(self.amount_minor, self.currency),
        }


def plan_offers() -> list[PlanOffer]:
    """What a user can buy. Prices are env-driven so a deployment can localize.

    The yearly offer is derived from the monthly price (× `PRO_YEAR_MONTHS`, i.e.
    two months free by default) rather than configured separately — one knob to
    change, and the discount can never drift out of sync with the base price.
    """
    monthly = max(0, int(settings.PRO_PRICE_MONTHLY_MINOR))
    cur = (settings.CURRENCY or "GHS").upper()
    offers = [
        PlanOffer("pro_monthly", "pro", "Pro · monthly", 1, monthly, cur),
        PlanOffer(
            "pro_yearly", "pro", "Pro · yearly", 12,
            monthly * max(1, int(settings.PRO_YEAR_MONTHS)), cur,
        ),
    ]
    return [o for o in offers if o.amount_minor > 0]


def offer_by_id(offer_id: str) -> PlanOffer | None:
    return next((o for o in plan_offers() if o.id == offer_id), None)


# ─────────────────────────────────────────────────────── providers

# Channel taxonomy. `manual` needs no integration at all; the rest are gateways
# that activate the moment their key is present.
PROVIDERS = ("manual", "paystack", "flutterwave", "stripe")

# Mobile money networks a manual payment method can advertise.
MOMO_NETWORKS = ("mtn", "vodafone", "airteltigo", "telecel")

METHOD_KINDS = ("momo", "bank", "cash", "other")


def provider_configured(provider: str) -> bool:
    """Does this deployment actually hold the keys for `provider`?"""
    p = (provider or "").lower()
    if p == "manual":
        return True  # manual is always available — that's the entire point
    if p == "paystack":
        return bool(settings.PAYSTACK_SECRET_KEY)
    if p == "flutterwave":
        return bool(settings.FLUTTERWAVE_SECRET_KEY)
    if p == "stripe":
        return bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PRICE_ID)
    return False


def providers() -> list[dict]:
    """Provider status for the UI — honest about what isn't wired up yet."""
    blurbs = {
        "manual": "Mobile money / bank transfer, verified by an admin",
        "paystack": "Cards + MoMo, auto-verified (needs PAYSTACK_SECRET_KEY)",
        "flutterwave": "Cards + MoMo, auto-verified (needs FLUTTERWAVE_SECRET_KEY)",
        "stripe": "International cards (needs STRIPE_SECRET_KEY + STRIPE_PRICE_ID)",
    }
    return [
        {
            "id": p,
            "label": p.title() if p != "manual" else "Mobile money / bank",
            "configured": provider_configured(p),
            "automatic": p != "manual",
            "description": blurbs[p],
        }
        for p in PROVIDERS
    ]


def default_provider() -> str:
    """Preferred channel: an automatic gateway if one is wired, else manual."""
    for p in ("paystack", "flutterwave", "stripe"):
        if provider_configured(p):
            return p
    return "manual"


# ─────────────────────────────────────────────────── reference codes

_REF_SAFE = re.compile(r"[^A-Za-z0-9._\- ]")


def clean_reference(raw: str | None) -> str:
    """Normalize a user-supplied transaction id for storage + duplicate checks.

    MoMo references are read off a phone screen and retyped, so we strip
    punctuation noise and upper-case them; comparing normalized forms is what
    makes duplicate detection actually work.
    """
    ref = _REF_SAFE.sub("", (raw or "").strip())
    return re.sub(r"\s+", " ", ref).upper()[:64]


def new_invoice_code() -> str:
    """Short human-quotable code the user puts in the MoMo reference field.

    Unambiguous alphabet (no O/0/I/1) because these get read aloud and retyped.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "CM-" + "".join(secrets.choice(alphabet) for _ in range(6))


# ─────────────────────────────────────────────────── period maths

def extend_period(current_end: datetime | None, months: int, *, now: datetime | None = None) -> datetime:
    """New expiry after paying for `months`.

    Extends from the LATER of now / the existing expiry, so renewing early adds
    to the remaining balance instead of silently discarding it. Approximates a
    month as 30 days — deliberate: a plan window doesn't need calendar-exact
    semantics, and 30 days is trivially explainable to a user.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = now
    if current_end is not None:
        end = current_end if current_end.tzinfo else current_end.replace(tzinfo=timezone.utc)
        base = max(now, end)
    return base + timedelta(days=30 * max(1, int(months)))


def is_expired(period_end: datetime | None, *, now: datetime | None = None) -> bool:
    """True when a paid period has lapsed. Naive datetimes (sqlite) read as UTC."""
    if period_end is None:
        return False
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = period_end if period_end.tzinfo else period_end.replace(tzinfo=timezone.utc)
    return end <= now


async def downgrade_expired_plans() -> int:
    """Return lapsed manual subscriptions to the free plan. Returns the count.

    Manual payments have no gateway webhook to tell us a period ended, so the
    platform has to notice by itself — otherwise a one-month manual payment
    would quietly grant Pro forever.
    """
    from sqlalchemy import select

    from ..db.models import Subscription, User
    from ..db.session import SessionLocal

    downgraded = 0
    try:
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(Subscription).where(
                        Subscription.status == "active",
                        Subscription.current_period_end.is_not(None),
                    )
                )
            ).scalars().all()
            for sub in rows:
                if not is_expired(sub.current_period_end):
                    continue
                # Never touch a gateway-managed subscription: Stripe owns that
                # lifecycle and its webhook is the source of truth.
                if sub.stripe_subscription_id:
                    continue
                sub.status = "expired"
                user = await db.get(User, sub.user_id)
                if user and user.plan != "free":
                    user.plan = "free"
                downgraded += 1
            if downgraded:
                await db.commit()
    except Exception as e:  # a sweep failure must never break the app
        log.warning("plan expiry sweep failed: %s", e)
    return downgraded
