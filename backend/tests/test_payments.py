"""💳 Payments — manual mobile money, admin review, plan activation.

The tests that matter most here guard money and authorization:
  • only an ADMIN approval may grant a plan (never the user's own submission),
  • approving twice must not hand out two months,
  • a transaction reference can only be claimed once,
  • paying early extends the period instead of discarding the remainder.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.models import Base, Payment, PaymentMethod, Subscription, User
from app.db.session import get_db
from app.main import app
from app.services import payments as pay

PW = "Payments-2026!"


def run(coro):
    return asyncio.run(coro)


# ══════════════════════════════════════════════════ pure money helpers

def test_to_minor_converts_without_float_drift():
    assert pay.to_minor("12.50") == 1250
    assert pay.to_minor(150) == 15000
    assert pay.to_minor(0.1) == 10
    # the classic float trap: 1.15 * 100 == 114.99999...
    assert pay.to_minor("1.15") == 115
    assert pay.to_minor("0") == 0


def test_to_minor_rejects_garbage_instead_of_zeroing():
    for bad in ("abc", None, "", "12.5.6"):
        with pytest.raises(ValueError):
            pay.to_minor(bad)


def test_to_minor_rejects_negative_amounts():
    with pytest.raises(ValueError):
        pay.to_minor("-5")


def test_format_money_is_readable():
    assert pay.format_money(15000, "GHS") == "150.00 GHS"
    assert pay.format_money(1250, "ghs") == "12.50 GHS"
    assert pay.format_money(123456789, "GHS") == "1,234,567.89 GHS"


# ══════════════════════════════════════════════════════ plan catalog

def test_yearly_offer_is_derived_from_the_monthly_price(monkeypatch):
    """One knob — the discount can never drift out of sync with the base price."""
    monkeypatch.setattr(settings, "PRO_PRICE_MONTHLY_MINOR", 15_000)
    monkeypatch.setattr(settings, "PRO_YEAR_MONTHS", 10)
    offers = {o.id: o for o in pay.plan_offers()}
    assert offers["pro_monthly"].amount_minor == 15_000
    assert offers["pro_yearly"].amount_minor == 150_000   # 10 × monthly
    assert offers["pro_yearly"].months == 12              # but grants 12 → 2 free


def test_free_pricing_hides_the_offers(monkeypatch):
    monkeypatch.setattr(settings, "PRO_PRICE_MONTHLY_MINOR", 0)
    assert pay.plan_offers() == []


def test_offer_lookup_by_id(monkeypatch):
    monkeypatch.setattr(settings, "PRO_PRICE_MONTHLY_MINOR", 15_000)
    assert pay.offer_by_id("pro_monthly").plan == "pro"
    assert pay.offer_by_id("nope") is None


# ═════════════════════════════════════════════════════════ providers

def test_manual_is_always_available_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "")
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "")
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "")
    assert pay.provider_configured("manual") is True
    assert pay.default_provider() == "manual"


def test_gateways_report_unconfigured_until_their_keys_land(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "")
    monkeypatch.setattr(settings, "FLUTTERWAVE_SECRET_KEY", "")
    assert pay.provider_configured("paystack") is False
    assert pay.provider_configured("flutterwave") is False

    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "sk_test_x")
    assert pay.provider_configured("paystack") is True
    assert pay.default_provider() == "paystack"   # auto gateway preferred once wired


def test_stripe_needs_both_key_and_price(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_live_x")
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID", "")
    assert pay.provider_configured("stripe") is False
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID", "price_x")
    assert pay.provider_configured("stripe") is True


def test_providers_listing_is_honest_about_what_is_missing(monkeypatch):
    monkeypatch.setattr(settings, "PAYSTACK_SECRET_KEY", "")
    by_id = {p["id"]: p for p in pay.providers()}
    assert by_id["manual"]["configured"] is True and by_id["manual"]["automatic"] is False
    assert by_id["paystack"]["configured"] is False
    # the option is still LISTED — "coming soon", not silently absent
    assert "PAYSTACK_SECRET_KEY" in by_id["paystack"]["description"]


# ═══════════════════════════════════════════════════════ references

def test_reference_normalization_survives_retyping():
    """MoMo refs are read off a phone screen — normalize before comparing."""
    assert pay.clean_reference("  mp2401.abc-99 ") == "MP2401.ABC-99"
    assert pay.clean_reference("ref#123!!") == "REF123"
    assert pay.clean_reference(None) == ""


def test_invoice_codes_are_unambiguous_and_unique():
    codes = {pay.new_invoice_code() for _ in range(200)}
    assert len(codes) > 190                      # effectively collision-free
    for c in codes:
        assert c.startswith("CM-") and len(c) == 9
        # no O/0/I/1 — these get read aloud and retyped
        assert not (set("O0I1") & set(c[3:]))


# ══════════════════════════════════════════════════════ period math

def test_new_subscription_runs_30_days_per_month():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert pay.extend_period(None, 1, now=now) == now + timedelta(days=30)
    assert pay.extend_period(None, 12, now=now) == now + timedelta(days=360)


def test_renewing_early_extends_rather_than_discarding_the_remainder():
    """Paying before expiry must ADD to the balance, not reset it."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    current_end = now + timedelta(days=20)          # 20 days still owed
    out = pay.extend_period(current_end, 1, now=now)
    assert out == current_end + timedelta(days=30)  # 50 days total, nothing lost


def test_renewing_after_lapse_starts_from_now():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    lapsed = now - timedelta(days=45)
    assert pay.extend_period(lapsed, 1, now=now) == now + timedelta(days=30)


def test_is_expired_handles_naive_datetimes():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert pay.is_expired(None, now=now) is False
    assert pay.is_expired(now - timedelta(days=1), now=now) is True
    assert pay.is_expired(now + timedelta(days=1), now=now) is False
    # sqlite round-trips drop tzinfo — read as UTC instead of raising
    assert pay.is_expired((now - timedelta(days=1)).replace(tzinfo=None), now=now) is True


# ═══════════════════════════════════════════════════════ API tests

@pytest.fixture()
def api(monkeypatch):
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
    monkeypatch.setattr(settings, "MANUAL_PAYMENTS_ENABLED", True)
    monkeypatch.setattr(settings, "PRO_PRICE_MONTHLY_MINOR", 15_000)
    monkeypatch.setattr(settings, "CURRENCY", "GHS")
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    import app.db.session as db_session

    monkeypatch.setattr(db_session, "SessionLocal", factory)
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


async def _make_admin(factory, email):
    async with factory() as s:
        u = (await s.execute(select(User).where(User.email == email))).scalar_one()
        u.is_admin = True
        await s.commit()
        return u.id


async def _publish_momo(c, admin_tok, label="MTN MoMo — main", number="0244123456"):
    r = await c.post(
        "/admin/payments/methods",
        json={"kind": "momo", "label": label, "network": "mtn",
              "account_name": "MoodAI Ltd", "account_number": number,
              "instructions": "Dial *170#, send to the number above, then paste the transaction ID."},
        headers=_h(admin_tok),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ─────────────────────────────────────────── admin payment methods

def test_admin_publishes_a_momo_method_and_users_see_it(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner@test.io")
            await _make_admin(factory, "owner@test.io")
            mid = await _publish_momo(c, admin)

            user = await _token(c, "buyer@test.io")
            opts = (await c.get("/payments/options", headers=_h(user))).json()
            assert [m["id"] for m in opts["methods"]] == [mid]
            assert opts["methods"][0]["account_number"] == "0244123456"
            assert opts["currency"] == "GHS"
            assert {o["id"] for o in opts["offers"]} == {"pro_monthly", "pro_yearly"}
            assert opts["offers"][0]["price_label"] == "150.00 GHS"

    run(go())


def test_non_admins_cannot_publish_or_review(api):
    async def go():
        async with await _client() as c:
            user = await _token(c, "nobody@test.io")
            assert (await c.get("/admin/payments/methods", headers=_h(user))).status_code == 403
            assert (await c.post("/admin/payments/methods",
                                 json={"kind": "momo", "label": "Mine", "account_number": "1"},
                                 headers=_h(user))).status_code == 403
            assert (await c.get("/admin/payments", headers=_h(user))).status_code == 403
            assert (await c.post("/admin/payments/grant",
                                 json={"user_id": "x", "plan": "pro"},
                                 headers=_h(user))).status_code == 403

    run(go())


def test_momo_method_requires_a_number(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner2@test.io")
            await _make_admin(factory, "owner2@test.io")
            r = await c.post("/admin/payments/methods",
                             json={"kind": "momo", "label": "Broken", "account_number": "  "},
                             headers=_h(admin))
            assert r.status_code == 422 and "number" in r.json()["detail"].lower()

    run(go())


def test_retiring_a_method_hides_it_from_users(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner3@test.io")
            await _make_admin(factory, "owner3@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "shopper@test.io")

            await c.patch(f"/admin/payments/methods/{mid}", json={"active": False}, headers=_h(admin))
            assert (await c.get("/payments/options", headers=_h(user))).json()["methods"] == []
            # but the admin still sees it, so history stays intelligible
            assert len((await c.get("/admin/payments/methods", headers=_h(admin))).json()["methods"]) == 1

    run(go())


def test_method_in_use_cannot_be_deleted(api):
    """Deleting a referenced destination would orphan historical payments."""
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner4@test.io")
            await _make_admin(factory, "owner4@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "payer4@test.io")
            await c.post("/payments/submit",
                         json={"offer_id": "pro_monthly", "method_id": mid, "reference": "TX-1"},
                         headers=_h(user))

            r = await c.delete(f"/admin/payments/methods/{mid}", headers=_h(admin))
            assert r.status_code == 409 and "inactive" in r.json()["detail"]

    run(go())


# ───────────────────────────────────────────────── user submission

def test_submitting_a_payment_does_not_grant_a_plan(api):
    """The critical authorization boundary: users cannot self-upgrade."""
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner5@test.io")
            await _make_admin(factory, "owner5@test.io")
            mid = await _publish_momo(c, admin)

            user = await _token(c, "sneaky@test.io")
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_monthly", "method_id": mid,
                                   "reference": "MP240101.9999", "payer_name": "Ama"},
                             headers=_h(user))
            assert r.status_code == 201
            assert r.json()["status"] == "pending"
            assert r.json()["amount_label"] == "150.00 GHS"
            # plan is untouched until an admin approves
            assert (await c.get("/auth/me", headers=_h(user))).json()["plan"] == "free"

    run(go())


def test_one_pending_payment_at_a_time(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner6@test.io")
            await _make_admin(factory, "owner6@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "impatient@test.io")

            body = {"offer_id": "pro_monthly", "method_id": mid, "reference": "TX-AAA"}
            assert (await c.post("/payments/submit", json=body, headers=_h(user))).status_code == 201
            r = await c.post("/payments/submit",
                             json={**body, "reference": "TX-BBB"}, headers=_h(user))
            assert r.status_code == 409 and "awaiting review" in r.json()["detail"]

    run(go())


def test_a_reference_can_only_be_claimed_once(api):
    """Two accounts must not be able to claim the same MoMo transaction."""
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner7@test.io")
            await _make_admin(factory, "owner7@test.io")
            mid = await _publish_momo(c, admin)

            a = await _token(c, "first@test.io")
            b = await _token(c, "second@test.io")
            body = {"offer_id": "pro_monthly", "method_id": mid, "reference": "MP-SHARED-1"}
            assert (await c.post("/payments/submit", json=body, headers=_h(a))).status_code == 201
            r = await c.post("/payments/submit", json=body, headers=_h(b))
            assert r.status_code == 409 and "already been submitted" in r.json()["detail"]

    run(go())


def test_reference_clash_is_case_and_punctuation_insensitive(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner8@test.io")
            await _make_admin(factory, "owner8@test.io")
            mid = await _publish_momo(c, admin)
            a = await _token(c, "typer1@test.io")
            b = await _token(c, "typer2@test.io")

            await c.post("/payments/submit",
                         json={"offer_id": "pro_monthly", "method_id": mid, "reference": "mp-2401-x"},
                         headers=_h(a))
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_monthly", "method_id": mid,
                                   "reference": "  MP-2401-X "},
                             headers=_h(b))
            assert r.status_code == 409

    run(go())


def test_unknown_offer_and_short_reference_are_rejected(api):
    async def go():
        async with await _client() as c:
            user = await _token(c, "bad@test.io")
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_lifetime", "reference": "TX-1"},
                             headers=_h(user))
            assert r.status_code == 422
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_monthly", "reference": "!!"},
                             headers=_h(user))
            assert r.status_code == 422

    run(go())


def test_manual_payments_can_be_disabled(api, monkeypatch):
    monkeypatch.setattr(settings, "MANUAL_PAYMENTS_ENABLED", False)

    async def go():
        async with await _client() as c:
            user = await _token(c, "off@test.io")
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_monthly", "reference": "TX-OFF"},
                             headers=_h(user))
            assert r.status_code == 503

    run(go())


# ─────────────────────────────────────────────────── admin review

async def _submit(c, user_tok, mid, ref="MP-OK-1"):
    r = await c.post("/payments/submit",
                     json={"offer_id": "pro_monthly", "method_id": mid, "reference": ref},
                     headers=_h(user_tok))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_approval_activates_the_plan(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner9@test.io")
            await _make_admin(factory, "owner9@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "happy@test.io")
            pid = await _submit(c, user, mid)

            # the payer's email is surfaced so an admin can match a MoMo alert
            queue = (await c.get("/admin/payments?status=pending", headers=_h(admin))).json()
            assert queue["pending_count"] == 1
            assert queue["payments"][0]["user_email"] == "happy@test.io"

            r = await c.post(f"/admin/payments/{pid}/approve",
                             json={"admin_note": "Seen in MoMo statement"}, headers=_h(admin))
            assert r.status_code == 200
            assert r.json()["status"] == "approved"
            assert r.json()["current_period_end"]

            assert (await c.get("/auth/me", headers=_h(user))).json()["plan"] == "pro"
            mine = (await c.get("/payments/mine", headers=_h(user))).json()
            assert mine["plan"] == "pro" and mine["subscription"] == "active"

    run(go())


def test_double_approval_does_not_grant_two_months(api):
    """A double-clicked Approve is the obvious way to give away free months."""
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner10@test.io")
            await _make_admin(factory, "owner10@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "double@test.io")
            pid = await _submit(c, user, mid)

            first = (await c.post(f"/admin/payments/{pid}/approve", json={}, headers=_h(admin))).json()
            end1 = first["current_period_end"]

            second = await c.post(f"/admin/payments/{pid}/approve", json={}, headers=_h(admin))
            assert second.status_code == 200 and second.json().get("already") is True

            async with factory() as s:
                u = (await s.execute(select(User).where(User.email == "double@test.io"))).scalar_one()
                sub = await s.scalar(select(Subscription).where(Subscription.user_id == u.id))
                assert sub.current_period_end.isoformat().startswith(end1[:19])  # unchanged

    run(go())


def test_rejection_leaves_the_user_on_free(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner11@test.io")
            await _make_admin(factory, "owner11@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "rejected@test.io")
            pid = await _submit(c, user, mid)

            r = await c.post(f"/admin/payments/{pid}/reject",
                             json={"admin_note": "No matching transaction"}, headers=_h(admin))
            assert r.status_code == 200 and r.json()["status"] == "rejected"
            assert (await c.get("/auth/me", headers=_h(user))).json()["plan"] == "free"
            # the reason reaches the user
            assert (await c.get("/payments/mine", headers=_h(user))).json()["payments"][0][
                "admin_note"] == "No matching transaction"

    run(go())


def test_rejected_payment_cannot_then_be_approved(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner12@test.io")
            await _make_admin(factory, "owner12@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "flip@test.io")
            pid = await _submit(c, user, mid)
            await c.post(f"/admin/payments/{pid}/reject", json={}, headers=_h(admin))
            r = await c.post(f"/admin/payments/{pid}/approve", json={}, headers=_h(admin))
            assert r.status_code == 409

    run(go())


def test_rejection_frees_the_user_to_resubmit(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner13@test.io")
            await _make_admin(factory, "owner13@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "retry@test.io")
            pid = await _submit(c, user, mid, ref="MP-TYPO")
            await c.post(f"/admin/payments/{pid}/reject", json={}, headers=_h(admin))
            # the "one pending at a time" rule must not lock them out forever
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_monthly", "method_id": mid,
                                   "reference": "MP-CORRECT"},
                             headers=_h(user))
            assert r.status_code == 201

    run(go())


def test_yearly_purchase_grants_twelve_months(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner14@test.io")
            await _make_admin(factory, "owner14@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "yearly@test.io")
            r = await c.post("/payments/submit",
                             json={"offer_id": "pro_yearly", "method_id": mid, "reference": "MP-YEAR"},
                             headers=_h(user))
            pid = r.json()["id"]
            assert r.json()["months"] == 12
            assert r.json()["amount_label"] == "1,500.00 GHS"   # 10 × 150

            out = (await c.post(f"/admin/payments/{pid}/approve", json={}, headers=_h(admin))).json()
            end = datetime.fromisoformat(out["current_period_end"])
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            assert (end - datetime.now(timezone.utc)).days > 300

    run(go())


# ──────────────────────────────────────────────── admin direct grant

def test_admin_can_grant_a_plan_without_payment(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner15@test.io")
            await _make_admin(factory, "owner15@test.io")
            await _token(c, "comped@test.io")
            async with factory() as s:
                target = (await s.execute(select(User).where(User.email == "comped@test.io"))).scalar_one()
                uid = target.id

            r = await c.post("/admin/payments/grant",
                             json={"user_id": uid, "plan": "pro", "months": 3,
                                   "admin_note": "Launch partner"},
                             headers=_h(admin))
            assert r.status_code == 200 and r.json()["plan"] == "pro"

            # an audit row explains WHY the account is Pro
            async with factory() as s:
                row = (await s.execute(select(Payment).where(Payment.user_id == uid))).scalars().first()
                assert row.status == "approved" and row.amount_minor == 0
                assert row.offer_id == "admin_grant" and "Launch partner" in row.admin_note

    run(go())


def test_admin_can_revoke_back_to_free(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner16@test.io")
            await _make_admin(factory, "owner16@test.io")
            await _token(c, "revoked@test.io")
            async with factory() as s:
                uid = (await s.execute(select(User).where(User.email == "revoked@test.io"))).scalar_one().id

            await c.post("/admin/payments/grant",
                         json={"user_id": uid, "plan": "pro", "months": 1}, headers=_h(admin))
            r = await c.post("/admin/payments/grant",
                             json={"user_id": uid, "plan": "free"}, headers=_h(admin))
            assert r.status_code == 200
            assert r.json()["plan"] == "free" and r.json()["current_period_end"] is None

    run(go())


def test_summary_reports_queue_and_revenue(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner17@test.io")
            await _make_admin(factory, "owner17@test.io")
            mid = await _publish_momo(c, admin)
            u1 = await _token(c, "rev1@test.io")
            u2 = await _token(c, "rev2@test.io")
            p1 = await _submit(c, u1, mid, ref="MP-R1")
            await _submit(c, u2, mid, ref="MP-R2")
            await c.post(f"/admin/payments/{p1}/approve", json={}, headers=_h(admin))

            s = (await c.get("/admin/payments/summary", headers=_h(admin))).json()
            assert s["approved"] == 1 and s["pending"] == 1
            assert s["collected_minor"] == 15_000
            assert s["collected_label"] == "150.00 GHS"

    run(go())


# ──────────────────────────────────────────────────── expiry sweep

def test_expiry_sweep_downgrades_lapsed_manual_plans(api):
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner18@test.io")
            await _make_admin(factory, "owner18@test.io")
            mid = await _publish_momo(c, admin)
            user = await _token(c, "lapsed@test.io")
            pid = await _submit(c, user, mid, ref="MP-LAPSE")
            await c.post(f"/admin/payments/{pid}/approve", json={}, headers=_h(admin))

            # wind the clock past the paid period
            async with factory() as s:
                u = (await s.execute(select(User).where(User.email == "lapsed@test.io"))).scalar_one()
                sub = await s.scalar(select(Subscription).where(Subscription.user_id == u.id))
                sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=1)
                await s.commit()

            assert await pay.downgrade_expired_plans() == 1
            assert (await c.get("/auth/me", headers=_h(user))).json()["plan"] == "free"

    run(go())


def test_sweep_leaves_unexpired_and_stripe_managed_plans_alone(api):
    """Stripe owns its own lifecycle — its webhook is the source of truth."""
    async def go():
        factory = api
        async with await _client() as c:
            admin = await _token(c, "owner19@test.io")
            await _make_admin(factory, "owner19@test.io")
            mid = await _publish_momo(c, admin)
            live = await _token(c, "live@test.io")
            pid = await _submit(c, live, mid, ref="MP-LIVE")
            await c.post(f"/admin/payments/{pid}/approve", json={}, headers=_h(admin))

            await _token(c, "stripey@test.io")
            async with factory() as s:
                su = (await s.execute(select(User).where(User.email == "stripey@test.io"))).scalar_one()
                su.plan = "pro"
                s.add(Subscription(
                    user_id=su.id, status="active", stripe_subscription_id="sub_123",
                    current_period_end=datetime.now(timezone.utc) - timedelta(days=5),
                ))
                await s.commit()

            assert await pay.downgrade_expired_plans() == 0
            assert (await c.get("/auth/me", headers=_h(live))).json()["plan"] == "pro"

    run(go())
