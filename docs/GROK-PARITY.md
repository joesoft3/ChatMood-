# 😄 Grok-parity pack

ChatMood already shipped the Grok core (live search, Think, DeepSearch, memory,
projects, tasks, Imagine/video, voice, agents). This pack closes the **user-facing
gaps** that still made the product feel one layer short of grok.com.

## What landed

| Grok feature | ChatMood |
| --- | --- |
| Fun mode | 😄 Toggle on the model row, Settings, and Flutter drawer. Persists as `users.fun_mode`. Per-turn `fun` on `/chat/stream`. |
| Temporary chat | 👻 Hidden from the sidebar, never written to memory or past-chat recall. `conversations.temporary`. |
| Edit memories | Settings → a fact → **Edit**. `PATCH /memory/{id}` re-embeds and swaps the point id. Chat digests stay read-only. |
| DeeperSearch | Deep / Deeper pills when Research mode is on. Same backend `depth` that already did 2×4 vs 3×5 rounds. |
| Canvas | **Canvas** on a long answer opens a side workspace: edit, copy, download, or send back to the composer. |
| KaTeX math | Answers render `$inline$` and `$$display$$` via remark-math + rehype-katex. |

## What this is *not*

Companions, voice cloning, Grok Bot always-on agents, native X posting, and
Build Mode app publishing are out of scope for a mergeable deploy. Tasks already
cover scheduled automations; plugins cover Gmail/Calendar/GitHub.

## API

- `PATCH /auth/preferences` `{fun_mode?: bool, custom_instructions?: string}` — partial.
- `POST /chat/stream` `{fun?: bool, temporary?: bool}` plus the existing fields.
- `PATCH /memory/{id}` `{fact, category?}` — 404 for missing, foreign, or chat-digest points.
- `GET /conversations` omits `temporary` rows. `GET /conversations/{id}` still works.

Migration `0029_grok_parity` is existence-guarded.

## Tests

`backend/tests/test_grok_parity.py` — Fun persists, temporary chats stay off the
history list and skip memory writes, normal chats still list + extract, `fun`
reaches `build_messages`, DeeperSearch depth table, memory rewrite drops the old id.
