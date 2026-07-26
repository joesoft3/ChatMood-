# 📚 ChatMood documentation index

Every guide in `docs/`, grouped by what you're trying to do. Start with
**[ARCHITECTURE.md](ARCHITECTURE.md)** for the technical blueprint, or jump to the
deploy path that matches your host.

> This index is machine-checked — `node scripts/check-docs.mjs` fails if a guide in
> `docs/` isn't listed here, if a relative link points at a missing file, or if a
> `#anchor` doesn't exist in its target document. Add a new guide → add a line here.
> See [wiring the gate into CI](#wiring-the-gate-into-ci) below.

---

## 🧭 Start here

| Guide | What it covers |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full technical blueprint: model routing, multi-agent design, plugin framework, scaling roadmap. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | The short path to a public URL in ~30 minutes. |
| [DEPLOY-WALKTHROUGH.md](DEPLOY-WALKTHROUGH.md) | The long-form production deploy, step by step. |
| [GO-LIVE-CLICKSHEET.md](GO-LIVE-CLICKSHEET.md) | Click-by-click go-live: Vercel or Railway → Netlify → phone. |

## ☁️ Hosting & infrastructure

| Guide | What it covers |
| --- | --- |
| [BACKEND-HOSTING.md](BACKEND-HOSTING.md) | Choosing where the FastAPI side answers real requests. |
| [DEPLOY-FLY.md](DEPLOY-FLY.md) | Fly.io — long renders and voice WebSockets welcome. |
| [DEPLOY-VERCEL.md](DEPLOY-VERCEL.md) | Vercel serverless backend deploy. |
| [NETLIFY-DEPLOY.md](NETLIFY-DEPLOY.md) | Netlify for the Next.js web app. |
| [RAILWAY-CHEATSHEET.md](RAILWAY-CHEATSHEET.md) | Railway click-sheet for this repo. |
| [DATABASE-OPTIONS.md](DATABASE-OPTIONS.md) | Where the database can live, and the trade-offs. |
| [SUPABASE.md](SUPABASE.md) | Supabase as the managed Postgres option. |
| [R2-STORAGE.md](R2-STORAGE.md) | Cloudflare R2 (S3-compatible, zero egress) file storage. |

## 🌍 Domains & white-label

| Guide | What it covers |
| --- | --- |
| [CUSTOM-DOMAIN-SETUP.md](CUSTOM-DOMAIN-SETUP.md) | Wiring `app.` (web) and `api.` (API) subdomains. |
| [CUSTOM-DOMAIN-SALES-PAGE.md](CUSTOM-DOMAIN-SALES-PAGE.md) | Custom domain + white-label arena quickstart. |
| [5BOOST-ME-CUTOVER.md](5BOOST-ME-CUTOVER.md) | The 5boost.me cutover plan. |

## 🎨 Product surfaces

| Guide | What it covers |
| --- | --- |
| [CREATOR-REEL.md](CREATOR-REEL.md) | 📺 Creator Reel — the shared vertical creator feed and reel studio. |
| [VIDEO-SOUND.md](VIDEO-SOUND.md) | 🎙 Cinema Sound — text-to-video with voiceovers and music. |
| [DESIGN-STUDIO.md](DESIGN-STUDIO.md) | 🖨 Flyers, stickers, banners and logos at print resolution. |
| [BATCH-AND-BEATS.md](BATCH-AND-BEATS.md) | 🔁 Batch Studio + 🎵 Beat-Sync. |
| [TEAMS-WALKTHROUGH.md](TEAMS-WALKTHROUGH.md) | 👥 Team workspaces walkthrough + test checklist. |
| [TASKS-PROJECTS-API.md](TASKS-PROJECTS-API.md) | ⏰ Scheduled tasks · 🗂 Projects · 🔑 the OpenAI-compatible developer API. |
| [QA-AUDIT.md](QA-AUDIT.md) | ✅ A–Z button/route audit, the offline wiring gate, and Play Store readiness. |
| [REEL-PREMIUM.md](REEL-PREMIUM.md) | ⭐ Creator Pro perks and 🔴 Go Live broadcasting on the Reel. |
| [PAYMENTS.md](PAYMENTS.md) | 💳 Manual mobile money, admin review, and adding Paystack/Flutterwave later. |
| [BRAND-ICONS.md](BRAND-ICONS.md) | 🎨 One lockup → every app/PWA/Android icon, with the maskable safe zone. |
| [WATERMARKING.md](WATERMARKING.md) | 🏷 Free-tier render badging — entitlement rules, where it applies, how to brand it. |
| [PLUGIN-OAUTH.md](PLUGIN-OAUTH.md) | 🔑 Gmail, Google Calendar and GitHub OAuth for real. |
| [ADMIN-ANALYTICS.md](ADMIN-ANALYTICS.md) | 📊 Admin analytics & engagement surfaces. |

## 📱 Mobile & store release

| Guide | What it covers |
| --- | --- |
| [MOBILE.md](MOBILE.md) | The Flutter client — Films screen & playback. |
| [UPLOAD-KEY.md](UPLOAD-KEY.md) | Generating the Play upload key (one time, 5 minutes). |
| [PLAY-CONSOLE.md](PLAY-CONSOLE.md) | Play Console listing pack. |
| [PLAY-STORE-SUBMISSION.md](PLAY-STORE-SUBMISSION.md) | Internal track → production submission run. |
| [PUSH-NOTIFICATIONS.md](PUSH-NOTIFICATIONS.md) | 🔔 FCM push blueprint. |
| [SCREENSHOT-CAPTURE.md](SCREENSHOT-CAPTURE.md) | Capturing UI screenshots for store listings. |

## 🔐 Auth, policy & compliance

| Guide | What it covers |
| --- | --- |
| [CLERK-AUTH-ASSESSMENT.md](CLERK-AUTH-ASSESSMENT.md) | Honest assessment of adopting Clerk. |
| [ACCOUNT-DELETION.md](ACCOUNT-DELETION.md) | 🗑 Account deletion — Play & App Store compliance. |
| [PRIVACY.md](PRIVACY.md) | Privacy policy. |
| [TERMS.md](TERMS.md) | Terms of service. |

## 🧪 Testing & operations

| Guide | What it covers |
| --- | --- |
| [LIVE-SMOKE.md](LIVE-SMOKE.md) | Live smoke runbook against a deployed stack. |

---

## Repository conventions

- **Docs live in `docs/`** as `SCREAMING-KEBAB-CASE.md`, each opening with a single
  `# Title` line — that title is what belongs in the table above.
- **Link relatively** (`[VIDEO-SOUND.md](VIDEO-SOUND.md)` from inside `docs/`,
  `[docs/VIDEO-SOUND.md](docs/VIDEO-SOUND.md)` from the repo root) so links survive
  on GitHub, in editors, and in any static export.
- **Changes that ship to `main` get a `CHANGELOG.md` entry** with the PR number.
- Run the housekeeping gate locally before opening a PR:

  ```bash
  node scripts/check-docs.mjs
  ```

---

## Wiring the gate into CI

The check is designed to be a third job in `.github/workflows/test.yml`, beside
`backend-unit` and `web-typecheck`. Append this job:

```yaml
  docs:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      # Offline + dependency-free: relative link/anchor integrity, docs index
      # coverage, and H1 titles. Never fetches external URLs, so it can't flake.
      - name: Docs housekeeping gate
        run: node scripts/check-docs.mjs
```

…and extend the workflow's path filters so markdown-only changes still trigger it:

```yaml
on:
  push:
    branches: [main]
    paths:
      - "backend/**"
      - "frontend/**"
      - "docs/**"
      - "scripts/check-docs.mjs"
      - "**/*.md"
      - ".github/workflows/test.yml"
  pull_request:
    paths:
      - "backend/**"
      - "frontend/**"
      - "docs/**"
      - "scripts/check-docs.mjs"
      - "**/*.md"
```

No `npm install` step is needed — the script uses only Node's standard library.
