# 📊 Admin analytics & engagement

The owner dashboard (`GET /admin/analytics`, `GET /admin/engagement`, `GET /admin/devices`) provides operational visibility into growth, usage, and the video/sound pipeline.

## Analytics endpoint (`/admin/analytics`)

Returns a 14-day series and 30-day aggregates:

| Section | Source | Notes |
|---|---|---|
| `signups_14d` | `User.created_at` daily count | 14-day rolling series |
| `active_14d` | `UsageEvent.user_id` distinct daily count | Active = at least one event that day |
| `usage_mix` | `UsageEvent.kind` counts + token sums (30d) | Includes `video`, `i2v`, `design`, `edit`, `film`, etc. |
| `arena` | `UsageEvent.kind == "arena"` (total, 7d, unique users) | Pro feature adoption |
| `revenue` | `User.plan == "pro"` × `Stripe` price | Best-effort; falls back to estimated price if Stripe not wired |
| `top_users_month` | Top 5 users by `UsageEvent.tokens_in + tokens_out` (month-to-date) | Email + token count |

The route requires `require_admin` (admin flag or `ADMIN_EMAILS` match).

## Engagement endpoint (`/admin/engagement`)

Focuses on the video/sound studio pipeline and push notifications (30-day window):

| Section | Metrics |
|---|---|
| `push` | `push_attempt:*` attempts, `push:*` delivered, `push_prune` tokens pruned, delivery rate |
| `studio_mix` | `video`, `i2v`, `design`, `edit`, `design_export`, `film` counts + rough USD cost |
| `studio_cost_usd` | Estimated cost per action (`video`: $0.12, etc.) |
| `design_kinds` | Design table `kind` counts (logo, poster, etc.) |
| `sound` | Videos generated (`video`) vs. sound-tracked (`media_sound`) = attach rate |
| `top_films` | Most-viewed finished films (`Film.views`, `scenes`, `created_at`) |
| `music_mix` | Music mood (`soft`, `epic`, `lofi`, `tension`) counts for finished films |
| `device_activity` | Registered devices (`Device.platform`, `email`, `created_at`, `last_seen_at`, events in 30d) |

### Push funnel

The `notify` service writes three kinds of `UsageEvent` rows:
- `push_attempt:{kind}` (e.g., `push_attempt:film_ready`)
- `push:{kind}` (delivered)
- `push_prune` (pruned tokens for 300s cooldown)

The `engagement` endpoint aggregates these by stripping the `push_` prefix and grouping by `kind`. The 30-day delivery rate is `delivered / attempts`.

### Studio cost estimation

A rough per-run cost table (`COSTS`) estimates studio spend: video ($0.12), image-to-video ($0.12), design ($0.04), edit ($0.05), film ($0.12), design export ($0.00). This is informational, not billing-grade.

## Devices endpoint (`/admin/devices`)

- Total device count and platform mix (`Device.platform`).
- Most recent 15 registrations with owner email, platform, created/last-seen timestamps.
- Used by the push test feature (`POST /admin/push-test`) which sends a real notification to the owner's registered devices.

## Owner controls related to analytics

- `GET /admin/settings` — sign-up gate (`signup_open`), app password (`app_password_set`), admin emails.
- `PUT /admin/settings` — rotate or clear the app access password; toggle open signups.
- `POST /admin/push-test` — sends a test push notification (`title`, `body`). Requires `FCM_PROJECT_ID` and `FCM_SERVICE_ACCOUNT_JSON` configured.

## Usage in the frontend

The owner panel (`/admin`) calls these endpoints to render:
- Overview tiles (users, conversations, messages, workspace count, active domains, token consumption).
- Growth chart (14-day signups + active users).
- Studio mix chart (video, design, edit counts + cost).
- Music mood mix chart (finished films by `music` field).
- Top films leaderboard (views + scene count + creation time).
- Device activity list (platform, owner, events in last 30 days).
