# Go Live — `arena/019f9b4e-moodai`

This document captures the go-live path for the `arena/019f9b4e-moodai` branch.

## Current state

- Branch `arena/019f9b4e-moodai` started identical to `main` (base commit
  `97317a44` — "Creator Reel + Reel button visibility everywhere (#18)").
- This commit is a **setup commit** to open the merge-to-production PR. It
  intentionally contains no feature/fix changes — it only documents the
  go-live procedure.
- Real changes should land on this branch as additional commits before merge.

## How production deploys

ChatMood auto-deploys from `main` via GitHub Actions (see `.github/workflows/`):

| Surface | Host       | Trigger                  | Config                       |
| ------- | ---------- | ------------------------ | ---------------------------- |
| Web     | Netlify    | push to `main`           | `netlify.toml`, `deploy-netlify.yml` |
| API     | Vercel     | push to `main`           | `deploy-vercel.yml`          |
| API     | Fly.io     | `fly deploy`             | `fly.toml`, `Dockerfile.fly`, `deploy-fly.yml` |
| Backend | Render     | Blueprint `autoDeploy`   | `render.yaml`                |

So the canonical "go live" step is: **merge this branch into `main`**, which
triggers the Netlify + Vercel production deploys.

## Required environment (all hosts)

- `XAI_API_KEY` — required (Grok models, Live Search, vision)
- `OPENAI_API_KEY` — voice features (realtime STT/TTS)
- `GEMINI_API_KEY` — widens the Arena panel
- `JWT_SECRET`, `REDIS_URL`, `DATABASE_URL`, `QDRANT_URL`
- Stripe: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`
- `CORS_ORIGINS`, `FRONTEND_URL`
- `APP_PASSWORD`, `ADMIN_BOOTSTRAP_PASSWORD` — **change before any public deploy**

See `.env.example` and `docs/DEPLOY-WALKTHROUGH.md` for the full setup.

## Smoke test after deploy

Run `scripts/live-smoke.sh` (or the `live-smoke.yml` workflow) against the
live URL to verify chat, search, memory, and `/readyz`.

## Steps to ship a real change

1. Implement the change on `arena/019f9b4e-moodai`, commit, and `git push`.
2. Open / update the PR against `main`.
3. Merge to `main` → production auto-deploys.
4. Run the live smoke test.

> Generated via Arena.ai Agent Mode to establish the go-live PR path.
