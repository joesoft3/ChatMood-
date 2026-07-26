# ⏰🗂🔑 Tasks · Projects · Developer API

Three Grok-parity surfaces that turn Mood from *something you ask* into
*something that works for you*:

| Surface | What it adds | Where it lives |
| --- | --- | --- |
| ⏰ **Scheduled tasks** | Saved prompts Mood runs unattended, on a schedule | `/tasks` |
| 🗂 **Projects** | Durable containers: standing brief + pinned docs + filed chats | `/projects` |
| 🔑 **Developer API** | OpenAI-compatible programmatic access with `mk_live_…` keys | Settings → API |

---

## ⏰ Scheduled tasks

### What it is

A task is a prompt plus a cadence. *"Every weekday at 07:00, brief me on AI
news."* Mood runs it while you sleep, appends the answer to a dedicated chat
thread, and pushes a notification when it's done.

### Scheduling model

Deliberately **cron-free**. A cron parser is a dependency plus a support burden
("why didn't `*/5 9-17 * * 1-5` fire?"), and the product only needs four shapes:

| Kind | Fires |
| --- | --- |
| `once` | one time, then the task disables itself |
| `hourly` | every hour at `:minute` |
| `daily` | every day at `hour:minute` UTC |
| `weekly` | same, restricted to a weekday mask (Mon=0 … Sun=6) |

All times are stored and computed in **UTC**; the web UI shows you the local
equivalent as you pick. The arithmetic lives in
[`backend/app/services/schedule.py`](../backend/app/services/schedule.py) as pure
functions, which is what makes it unit-testable without a clock or a database
(see `backend/tests/test_schedule.py`).

### Modes

A task runs through one of three engines:

- **`chat`** — a normal grounded turn, with your full context stack (memory,
  past-chat recall, doc-RAG, and the project brief if the task belongs to one).
- **`deepsearch`** — multi-round agentic web research, synthesized with citations.
- **`agent`** — the research team (researcher/coder → writer) produces the answer.

### How the scheduler stays correct

Four properties, each of which is a bug someone else has shipped:

1. **Single loop, atomic claim.** Every tick selects due tasks and claims each
   with a conditional `UPDATE … WHERE last_status != 'running'`. Two app
   instances racing the same row: exactly one `UPDATE` matches. Fly runs several
   machines — leaving `SCHEDULER_ENABLED=true` everywhere is safe.
2. **The clock advances at claim time, not after the work.** If the process dies
   mid-run, the task resumes on its next slot instead of hot-looping on a
   permanently-overdue row.
3. **Runs are bounded.** `SCHEDULER_RUN_TIMEOUT_S` caps a single execution, and
   every run is metered as a `task` usage event — so an unattended job can't
   quietly drain an account overnight.
4. **Failures are inert.** A failing task records `last_status='failed'` with the
   error, keeps its schedule, and never blocks its siblings or kills the loop.

`GET /healthz` reports `scheduler: {enabled, running, ticks, runs, last_tick}`
so you can verify the loop without log access.

### API

```
GET    /api/v1/tasks               list (cadence labels + next run)
POST   /api/v1/tasks               create
GET    /api/v1/tasks/{id}          detail + last 20 runs
PATCH  /api/v1/tasks/{id}          edit / pause / resume (recomputes next_run_at)
DELETE /api/v1/tasks/{id}          delete
POST   /api/v1/tasks/{id}/run      run right now — does NOT consume the next slot
```

Plan caps are enforced at **create** time (`TASK_MAX_PER_USER_FREE`, `…_PRO`)
rather than at fire time: an unattended job that outgrew its plan should fail
when you're looking at the screen, not silently at 3am.

---

## 🗂 Projects

### What it is

A project is a durable container for work that spans many chats — a launch, a
thesis, a client. It carries three things:

- **Standing instructions** — prepended as a system message to *every* chat in
  the project, on every turn.
- **Pinned documents** — the project's own knowledge base, reachable from any
  chat inside it without re-attaching.
- **Filed chats** — conversations that belong to the project.

The point is that the brief is **ambient**. You set it once instead of
re-explaining your context at the top of every new conversation.

### How context is assembled

[`services/projects.py`](../backend/app/services/projects.py) contributes system
messages that `build_messages()` inserts **directly after the persona** — so the
standing brief outranks retrieved memory, doc-RAG and chat history:

```
[persona + custom instructions]
[project brief]              ← project.name / description / instructions
[project pinned documents]   ← up to 6 files × 4k chars
[known user facts]           (memory)
[previous conversations]     (recall)
[document excerpts]          (doc-RAG)
… history … new message
```

Budgets are deliberate: projects are long-lived and accumulate files, so an
unbounded splice would silently push the actual conversation out of the context
window.

The **conversation's** `project_id` is what drives injection — not the request's
— so a filed chat keeps its brief on every turn, not just the one that created it.

Everything is **fail-open**: a project lookup that errors degrades to a normal,
unfiled chat rather than breaking the conversation.

### Deleting is non-destructive

Deleting a project unfiles its chats and unpins its files. **Neither is
deleted.** Removing an organizational container must never be a destructive act
on real content — `test_deleting_a_project_unfiles_chats_but_keeps_them` pins
that behaviour.

### API

```
GET    /api/v1/projects                              list (+ chat/file/task counts)
POST   /api/v1/projects                              create
GET    /api/v1/projects/{id}                         detail + chats + pinned files
PATCH  /api/v1/projects/{id}                         rename / re-brief / archive
DELETE /api/v1/projects/{id}                         delete (content survives)
POST   /api/v1/projects/{id}/files/{fid}             pin a file
DELETE /api/v1/projects/{id}/files/{fid}             unpin
POST   /api/v1/projects/{id}/conversations/{cid}     file a chat
DELETE /api/v1/projects/{id}/conversations/{cid}     unfile
```

Owners may mutate; workspace members may **read**, so a team can share a brief
without anyone silently rewriting it.

Start a chat inside a project from the web app with `/chat?project=<id>`.

---

## 🔑 Developer API

### Why OpenAI-compatible

Because it means every existing SDK — `openai-python`, the Vercel AI SDK,
LangChain, curl snippets people already have — works by changing two strings.
A bespoke schema would be strictly more work for us and strictly less useful to
them.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://your-api.example.com/api/v1/public",
    api_key="mk_live_…",
)

resp = client.chat.completions.create(
    model="mood-flagship",
    messages=[{"role": "user", "content": "Explain quantum tunnelling"}],
)
print(resp.choices[0].message.content)
```

Streaming works too (`stream=True`) — the server emits standard
`chat.completion.chunk` frames terminated by `data: [DONE]`.

### Model aliases

| Alias | Backed by |
| --- | --- |
| `mood-flagship` | `MODEL_CHAT` (grok-4) |
| `mood-fast` | `MODEL_CHAT_FAST` |
| `mood-mini` | `MODEL_FAST` |
| `mood-code` | `MODEL_CODE` |

Callers pin a stable alias; we keep the freedom to re-point it (or fail it over)
underneath. An **unknown** alias falls back to the flagship rather than erroring
— an integration shouldn't break because it pinned a name we later retired.

### Endpoints

```
GET  /api/v1/public/models              the catalogue (OpenAI `list` shape)
POST /api/v1/public/chat/completions    chat, `stream: true` supported
POST /api/v1/public/search              grounded answer + structured citations
POST /api/v1/public/images              image generation
GET  /api/v1/public/usage               the calling account's meters
```

`/search` and `/usage` are Mood extensions; the rest is stock-shaped.

### Key security

- Only **`sha256(secret)`** is stored. A dump of the `api_keys` table yields
  nothing usable.
- The plaintext exists exactly once — in the response that created it. There is
  no endpoint that can show it again.
- `prefix` (first 11 chars) is kept in the clear purely so the UI can label rows.

**Why SHA-256 and not bcrypt/argon2** (which we *do* use for passwords): an API
key is 32 bytes of `secrets.token_urlsafe` entropy, not a human-chosen password,
so it isn't brute-forcible and there's nothing for a slow KDF to protect. Fast
hashing is also what lets us authenticate with a single indexed lookup per
request instead of a per-request KDF.

**Session JWTs are rejected** on `/public/*`, and API keys aren't accepted on the
session surfaces. Browser tokens live in localStorage and are handed to far more
code than a deliberately-minted, revocable, scoped key — keeping the surfaces
separate is what makes revoking a key actually revoke that integration's access.

### Scopes & limits

| Scope | Unlocks |
| --- | --- |
| `chat` | `/chat/completions` |
| `search` | `/search`, and `search: true` on completions |
| `images` | `/images` |

Unknown scopes are dropped rather than rejected (a client asking for a future
scope still gets a working key). Rate limiting is per key
(`API_KEY_RATE_PER_MIN`, times the plan multiplier), and every call is metered
as an `api` usage event — so programmatic traffic shows up in the same usage
dashboard and counts against the same plan.

Revocation is a soft flag, not a row delete: the key stops working immediately,
and the row survives so "who called us 40k times last month" stays answerable.

---

## Configuration

```bash
# 🗂 Projects
PROJECTS_ENABLED=true
PROJECT_MAX_FILES=40
PROJECT_MAX_PER_USER=100

# ⏰ Tasks
TASKS_ENABLED=true
SCHEDULER_ENABLED=true        # safe on every replica — claiming is atomic
SCHEDULER_TICK_S=60
SCHEDULER_BATCH=10
SCHEDULER_RUN_TIMEOUT_S=300
TASK_MAX_PER_USER_FREE=3
TASK_MAX_PER_USER_PRO=30

# 🔑 Developer API
PUBLIC_API_ENABLED=true
API_KEY_MAX_PER_USER=10
API_KEY_RATE_PER_MIN=60
```

Each surface can be switched off independently; the routes then answer `503`
with an explanation and the UI hides the card.

## Migration

```bash
cd backend && alembic upgrade head   # 0024_projects_tasks_keys
```

Creates `projects`, `project_files`, `scheduled_tasks`, `task_runs`, `api_keys`
and adds `conversations.project_id`. Every step is existence-guarded, so it is
re-runnable and safe on deployments whose tables came from
`Base.metadata.create_all`.

## Tests

```bash
cd backend && python -m pytest tests/test_schedule.py tests/test_projects.py \
                              tests/test_tasks.py tests/test_apikeys.py -q
```

62 tests covering schedule arithmetic, project context injection and
non-destructive deletes, the atomic claim and unattended runs, and key
hashing/scopes/revocation plus the OpenAI envelope shape.
