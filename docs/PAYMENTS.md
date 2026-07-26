# 💳 Payments

Ghana-first. **Manual mobile money works today with zero API keys**; Paystack,
Flutterwave and Stripe drop into the same flow the moment their keys exist.

```
admin publishes a MoMo number  →  user pays from their phone
   →  user submits the transaction ID  →  admin verifies  →  plan activates
```

## Why manual first

Stripe is card-only and awkward for this market. MoMo is how people actually
pay in Ghana, and the manual loop needs **no integration at all** — so revenue
can start before a single gateway contract is signed. Paystack and Flutterwave
both settle Ghanaian MoMo and are the natural next step; they write the same
`Payment` row, so nothing downstream changes when they're switched on.

## For the admin

**Owner panel → 💳 Payments.**

1. **Publish a destination** — MoMo number, bank account or cash. Add
   instructions ("Dial `*170#` → Send Money → …"); users see them verbatim.
2. **Review the queue** — each row shows the payer's email, the amount, the
   transaction reference and their phone, so you can match it against the MoMo
   alert on your phone.
3. **Approve** → the plan activates instantly and the period extends.
   **Reject** → the user sees your reason and can resubmit.

Extra tools:

- **Retire vs delete.** Retiring hides a number from users but keeps history
  readable. Deleting is refused (`409`) while payments reference it.
- **Direct grant** (`POST /admin/payments/grant`) — comp an account or fix a
  refund with no money involved. It still writes an `approved` payment of
  amount 0, so the audit trail always explains why an account is Pro.

## For the user

**Settings → Upgrade** (or `/upgrade`): pick monthly/yearly, copy the MoMo
number, send the money, paste the transaction ID. The page polls while an admin
confirms, then flips to Pro.

## Rules that protect the money

| Rule | Why |
| --- | --- |
| Submitting **never** grants a plan — only admin approval does | otherwise anyone self-upgrades with a made-up reference |
| Approval is **idempotent** | a double-clicked Approve must not hand out two months |
| A transaction reference can be claimed **once** | two accounts can't claim the same MoMo payment |
| References are normalized before comparison | refs are retyped off a phone screen — `mp-24x` and `  MP-24X ` are the same payment |
| **One** pending payment per user | stops five duplicate requests for one transfer |
| Periods **extend**, never reset | renewing early adds to the remaining balance |
| Amounts are integer **minor units** (pesewas) | `1.15 × 100 = 114.999…` in float; money never touches floats |

## Expiry

Gateways fire a webhook when a subscription ends. A manual MoMo payment has
nobody to fire anything, so a background sweep
(`PAYMENT_EXPIRY_SWEEP_HOURS`, default 6h) returns lapsed accounts to free —
otherwise one month of MoMo would grant Pro forever. Stripe-managed
subscriptions are skipped: its webhook is the source of truth for those.
State is visible on `/healthz` under `payment_sweep`.

## Pricing

```bash
CURRENCY=GHS
PRO_PRICE_MONTHLY_MINOR=15000   # 150.00 GHS in pesewas
PRO_YEAR_MONTHS=10              # yearly = 10× monthly, grants 12 → 2 free
```

The yearly price is *derived* from the monthly one, so the discount can never
drift out of sync with the base price.

## Adding Paystack / Flutterwave later

```bash
PAYSTACK_SECRET_KEY=sk_live_…
FLUTTERWAVE_SECRET_KEY=FLWSECK-…
```

`services/payments.providers()` reports each channel's readiness, and
`default_provider()` prefers an automatic gateway once one is configured.
Until then the UI honestly shows "needs key" instead of hiding the option.
Manual review stays available regardless — useful as a fallback when a
gateway is down.

## Migration

```bash
cd backend && alembic upgrade head   # 0026_payments
```

Creates `payment_methods` and `payments`. Guarded and re-runnable.

## Tests

```bash
cd backend && python -m pytest tests/test_payments.py -q   # 39 tests
```

Money maths (including the `1.15` float trap), the plan catalog, provider
readiness, reference normalization, period extension, and the full API path:
authorization boundaries, duplicate references, idempotent approval, rejection
and resubmission, admin grants, revenue summary, and the expiry sweep.
