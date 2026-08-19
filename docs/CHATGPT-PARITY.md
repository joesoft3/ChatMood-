# 🤖 ChatGPT-parity pack

ChatMood already shipped the ChatGPT core (streaming chat, Search, Deep
Research, Canvas, Projects, Memory, Custom Instructions, file analysis, voice,
Tasks, share links). This pack closes the **user-facing gaps** that still made
the product feel one layer short of chatgpt.com.

## What landed

| ChatGPT feature | ChatMood |
| --- | --- |
| Custom GPTs | `/gpts` store. Catalog starters (Writing Coach, Code Reviewer, Interview Prep, Data Analyst, Study Tutor, Meeting Notes, Email Pro, Daily Pulse) plus private user-built GPTs with instructions, starters and knowledge files. `/chat?gpt=` starts a thread that keeps that brief. |
| Study mode | 📚 Toggle on the model row, Settings, and Flutter drawer. Persists as `users.study_mode`. Per-turn `study` on `/chat/stream`. Socratic tutor — hints first, then a quiz. |
| Archive chats | Sidebar archive. Hidden from live history, not deleted. `conversations.archived`. Restore from the Archived list. |
| Full-text search | Sidebar search hits **titles and message bodies**. `GET /conversations/search?q=`. |
| Thumbs up / down | Rate an assistant turn. Stored on `message.meta.feedback`. |
| Continue generating | **Continue** on the last answer appends to that bubble. No extra user turn. |
| Duplicate chat | Toolbar **Duplicate** forks the thread (`POST /conversations/{id}/duplicate`). |
| Export JSON | `GET /conversations/{id}/export?format=json\|md` plus the existing client Markdown export. |
| Pulse | Honest Pulse: the Daily Pulse catalog GPT + **Schedule daily Pulse** creates a real 08:00 UTC task with live search. Not a fake always-on agent. |
| ChatGPT home | Empty `/chat` is the chatgpt.com home: left rail (New chat, Images, GPTs, Projects, Library, dated history, account), header model dropdown, centered **What can I help with?**, calm `+` composer, starter chips. Logged-in visitors skip the marketing page. |

## What this is *not*

ChatGPT Atlas (in-browser agent), Codex cloud workspaces, voice cloning,
computer-use Agent Mode, and a public GPT Store of other people's GPTs are out
of scope for a mergeable deploy. Tasks already cover scheduled automations;
plugins cover Gmail/Calendar/GitHub; Arena covers multi-model debate.

## API

- `PATCH /auth/preferences` `{study_mode?: bool, …}` — still partial.
- `POST /chat/stream` `{study?: bool, gpt_id?: str, continue_gen?: bool}`.
- `GET/POST/PATCH/DELETE /gpts[/{id}]` plus `/gpts/{id}/files/{fid}`.
- `GET /conversations?archived=true` · `GET /conversations/search?q=` ·
  `PATCH /conversations/{id}` `{archived}` · `POST …/duplicate` ·
  `GET …/export` · `POST …/messages/{mid}/feedback`.

Migration `0030_chatgpt_parity` is existence-guarded.

## Tests

`backend/tests/test_chatgpt_parity.py` — Study persists, catalog + owned GPT
CRUD and cross-tenant 404, GPT brief reaches `build_messages`, archive hides
from the live list, search hits message bodies, feedback / duplicate / export /
continue (no extra user turn).
