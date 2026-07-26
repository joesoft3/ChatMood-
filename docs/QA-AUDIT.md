# ✅ A–Z audit & Play Store readiness

What was checked, what broke, and what's left before you can publish.

## The gate

```bash
# 1. export the live route table from FastAPI
cd backend && python -c "import os;os.environ['DATABASE_URL']='sqlite+aiosqlite:///:memory:';\
import json;from app.main import app;json.dump(sorted(app.openapi()['paths']),open('../.routes.json','w'))"

# 2. verify every button leads somewhere real
node scripts/check-wiring.mjs
```

`scripts/check-wiring.mjs` catches the three ways a control can be dead — offline,
with no browser and no running server:

1. **API path doesn't exist** — every `apiFetch("/x")` is matched against the real
   FastAPI route table. Template literals (`/tasks/${id}`) are resolved
   structurally, and `${cond ? "approve" : "reject"}` is *expanded* so both
   branches get verified rather than waved through.
2. **Internal link 404s** — every `href="/x"` must map to a real page under
   `app/`, including `[dynamic]` segments.
3. **Button does nothing** — a `<button>` with no `onClick`, `type="submit"`,
   `form=` or `disabled` is almost certainly unfinished.

Current status: **67 files · 23 page routes · 153 API routes · 0 problems.**

The checker was validated by deliberately injecting each bug class (a typo'd API
path, a link to a nonexistent page, a handler-less button) and confirming all
three were caught.

## Bugs found and fixed

Both were **live 500s** that unit tests missed, because the offending line only
executes when a real request hits it.

| Bug | Impact | Fix |
| --- | --- | --- |
| `settings.MODELS_VIDEO` (4×) — that setting never existed; it's `MODEL_VIDEO` | `POST /media/videos/grok` and `GET /media/videos/grok-info` raised `AttributeError` → 500 | corrected to `MODEL_VIDEO` |
| `NEGATIVE_DEFAULT` used in `routes/media.py` but never imported | `GET /media/videos/grok-info` raised `NameError` → 500 (hidden *behind* the first bug) | added to the import |

Both are now locked by `tests/test_wiring_audit.py`, which scans every route
module for **undefined `settings.*` attributes** and **undefined SCREAMING_CASE
constants**. Re-introducing either bug fails the suite — verified.

## Runtime sweep

30 signed-in surfaces + 9 admin surfaces exercised end-to-end against a real
ASGI app. All return 200. Authorization was checked too:

- unauthenticated → **401** on `/conversations`, `/admin/overview`, `/reels/premium`
- normal user → **403** on `/admin/overview`

Three endpoints return 503 in the sandbox **by design**, not as faults:
`/readyz` and `/memory` need Redis/Qdrant, and `/media/films/resumable` uses the
app's own session factory. All three behave correctly against a real deployment.

## Generated media is now manageable

Every AI generation (chat images/videos, the Images studio) is archived as a
`FileAsset` — but the id was **discarded**, so the only handle the client had was
a presigned URL that expires after `IMAGE_PERSIST_TTL_S` (7 days). Download
silently rotted, and delete didn't exist at all.

`_persist_generated_media()` now returns `(url, stored, file_id)`, and that id
reaches the client on both the SSE media event and `POST /chat/image`. With it:

| Action | Route | Notes |
| --- | --- | --- |
| ⬇ Download | `GET /files/{id}/download` | stable — never expires, unlike the presigned render URL |
| ✏️ Edit | composer prefill / prompt reload | remixes via the existing media-refine router |
| 🗑 Delete | `DELETE /files/{id}` | removes the row, the bytes and the vector chunks |

Downloads go through `lib/download.ts` rather than `<a download>`: the stable
route is cross-origin and Bearer-authenticated, so a plain anchor would 401 or
silently *navigate* instead of saving. It fetches to a Blob, names the file from
the prompt, and falls back to opening a tab if the fetch is blocked.

When archiving fails the generation still succeeds — `file_id` is `""` and the
UI hides the manage actions rather than showing buttons that 404.

---

## 📱 Play Store readiness

### Already in place

| Requirement | Status |
| --- | --- |
| App Bundle (`.aab`, not APK) | ✅ `flutter build appbundle --release` |
| Target API level (Play requires ≥ 35) | ✅ `targetSdk 36` |
| R8 minification + resource shrinking | ✅ |
| Obfuscation + split debug symbols | ✅ |
| Upload signing from repo secrets | ✅ |
| **Account deletion** (mandatory) | ✅ in-app `/account-deletion` + public `DELETE /auth/me` |
| Privacy policy + Terms | ✅ `/privacy`, `/terms` (public URLs) |
| Data safety / content rating notes | ✅ `docs/PLAY-STORE-SUBMISSION.md` |
| Feature graphic + screenshots | ✅ `store-assets/` |

### Fixed here

**`POST_NOTIFICATIONS` was missing from the manifest.** Since Android 13 (API 33)
it's a runtime permission: `messaging.requestPermission()` was being called, but
with nothing declared the dialog never appeared and **every push was dropped
silently** — the app looked fine, notifications just never arrived.

`scripts/android-manifest-perms.py` now owns the permission set (INTERNET,
RECORD_AUDIO, POST_NOTIFICATIONS, CAMERA), each with an inline justification for
the reviewer. `android/` is regenerated by `flutter create` on every CI run, so
this must be re-applied per build:

```yaml
- name: Grant runtime permissions (release manifest)
  run: python3 ../scripts/android-manifest-perms.py \
         mobile/android/app/src/main/AndroidManifest.xml
```

> ⚠️ **This workflow edit is not committed.** This session's GitHub App lacks the
> `workflows` permission, so `.github/workflows/mobile-apk.yml` cannot be pushed
> from here. The script is in the repo and tested; swap the inline Python block
> at `mobile-apk.yml` → *"Grant runtime permissions"* for the call above.

### Before you submit

- [ ] **Apply the workflow edit above** — otherwise Android 13+ push stays broken.
- [ ] Set a real price: `PRO_PRICE_MONTHLY_MINOR` is a placeholder 150 GHS.
- [ ] **Google Play Billing.** Play requires its own billing for digital goods
      sold *inside* the app. The mobile client currently has no purchase flow, so
      today it complies by not selling in-app. If you add one, it must use Play
      Billing — MoMo/Paystack is fine on the **web**, not in the Android app.
- [ ] Declare in Data safety: account/email, user content (chats, uploads),
      approximate usage analytics — all deletable via the account-deletion flow.
- [ ] Content rating questionnaire: this is user-generated-content + AI
      generation; expect a Teen rating and be ready to describe moderation.
- [ ] Replace `store-assets/chatmood-lockup.png` with your original logo file and
      re-run `scripts/brand_icons.py` (the current art is a reconstruction).

## Tests

```bash
cd backend && python -m pytest tests/test_wiring_audit.py -q   # 3 tests
node scripts/check-wiring.mjs                                  # wiring gate
python3 scripts/android-manifest-perms.py <manifest>           # idempotent
```
