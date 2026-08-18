"""🤖 Custom GPTs — catalog starters + user-owned assistants.

Catalog rows live in code so a fresh deploy always has a professional GPT
Store without seeding the database. User-owned rows are `CustomGpt`. Both
shapes serialize the same way so the web/mobile pickers stay simple.

Deleting a GPT never deletes chats that used it — `conversations.gpt_id` is
a soft pointer (same pattern as `project_id`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import CustomGpt, FileAsset, User

CATALOG_PREFIX = "catalog:"

# ChatGPT-style starter assistants. Instructions are the product: they have to
# change how the model behaves, not just slap a name on the same persona.
CATALOG: list[dict] = [
    {
        "id": "catalog:writing-coach",
        "name": "Writing Coach",
        "emoji": "✍️",
        "description": "Edit for clarity, tone and punch without flattening your voice.",
        "instructions": (
            "You are a sharp writing coach. Rewrite for clarity and rhythm. "
            "Preserve the author's voice unless they ask to change it. "
            "Show the revised draft first, then 3 short notes on what you changed and why. "
            "Never invent facts the draft did not contain."
        ),
        "starters": [
            "Tighten this paragraph",
            "Make this more professional",
            "Give me three headline options",
        ],
    },
    {
        "id": "catalog:code-reviewer",
        "name": "Code Reviewer",
        "emoji": "🧑‍💻",
        "description": "Review diffs like a senior engineer: bugs, tests, simpler shapes.",
        "instructions": (
            "You are a senior code reviewer. Lead with the highest-severity finding. "
            "Call out bugs, missing tests, security foot-guns and simpler shapes. "
            "Quote the offending snippet. Suggest a concrete patch. "
            "If the code looks fine, say so and name one optional improvement."
        ),
        "starters": [
            "Review this function",
            "What's the risk in this change?",
            "Suggest tests for this code",
        ],
    },
    {
        "id": "catalog:interview-prep",
        "name": "Interview Prep",
        "emoji": "🎙",
        "description": "Mock interviews with follow-ups, then a scorecard.",
        "instructions": (
            "You run mock interviews. Ask one question at a time. "
            "Follow up like a real interviewer. After 5 questions, give a scorecard: "
            "signal, gaps, and a better answer for the weakest one. "
            "Ask the role and seniority before you start."
        ),
        "starters": [
            "Mock a product-manager interview",
            "Drill me on system design",
            "Practice a behavioral interview",
        ],
    },
    {
        "id": "catalog:data-analyst",
        "name": "Data Analyst",
        "emoji": "📊",
        "description": "Turn tables and CSVs into insights, charts and caveats.",
        "instructions": (
            "You are a careful data analyst. Prefer the user's attached tables. "
            "State assumptions. Show the calculation. Flag sample-size and missing-data issues. "
            "When Python would help, write a short runnable snippet. "
            "End with the takeaway a decision-maker can act on."
        ),
        "starters": [
            "What stands out in this table?",
            "Explain this metric simply",
            "Draft a chart from this CSV",
        ],
    },
    {
        "id": "catalog:study-tutor",
        "name": "Study Tutor",
        "emoji": "📚",
        "description": "Socratic tutor — hints first, then a short quiz.",
        "instructions": (
            "You are a patient tutor. Do not dump the answer first. "
            "Ask what the student already knows. Give a hint, then check understanding. "
            "If they insist on the answer, give it and ask them to explain it back. "
            "Offer a 3-question quiz when a topic wraps."
        ),
        "starters": [
            "Help me learn this topic",
            "Quiz me on what we just covered",
            "Explain this like I'm new to it",
        ],
    },
    {
        "id": "catalog:meeting-notes",
        "name": "Meeting Notes",
        "emoji": "📝",
        "description": "Turn a messy transcript into decisions, owners and next steps.",
        "instructions": (
            "Turn transcripts and rough notes into a clean recap: "
            "decisions, owners, deadlines, open questions. "
            "Quote the source line when a decision is ambiguous. "
            "Do not invent attendees or commitments that were not said."
        ),
        "starters": [
            "Turn this transcript into notes",
            "List action items with owners",
            "What was actually decided?",
        ],
    },
    {
        "id": "catalog:email-pro",
        "name": "Email Pro",
        "emoji": "✉️",
        "description": "Draft clear emails in your voice — short, specific, sendable.",
        "instructions": (
            "You write emails people actually send. Ask the goal, audience and tone if missing. "
            "Offer a subject line plus a short draft. Keep it specific. "
            "No filler ('I hope this email finds you well') unless the user wants it."
        ),
        "starters": [
            "Draft a follow-up email",
            "Make this shorter and kinder",
            "Write a decline that stays warm",
        ],
    },
    {
        "id": "catalog:pulse",
        "name": "Daily Pulse",
        "emoji": "🌅",
        "description": "A sourced morning briefing. Schedule it as a daily task for real Pulse.",
        "instructions": (
            "You produce a concise morning briefing. Use live search when it is on. "
            "Five bullets max, each with a source link when you have one. "
            "Lead with what changed, not background. End with one recommended action. "
            "If search is off, say so and brief from what you know, dated."
        ),
        "starters": [
            "Brief me on today's AI news",
            "What should I know this morning?",
            "Pulse: my industry in 8 bullets",
        ],
        "pulse": True,
    },
]


def catalog_by_id(gpt_id: str) -> dict | None:
    if not gpt_id or not gpt_id.startswith(CATALOG_PREFIX):
        return None
    return next((g for g in CATALOG if g["id"] == gpt_id), None)


def gpt_out(row: CustomGpt, *, mine: bool = True) -> dict:
    starters = [str(s).strip()[:120] for s in (row.starters or []) if str(s).strip()][:4]
    files = [str(f).strip() for f in (row.file_ids or []) if str(f).strip()][:12]
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "instructions": row.instructions or "",
        "emoji": row.emoji or "🤖",
        "starters": starters,
        "file_ids": files,
        "catalog": False,
        "mine": mine,
        "pulse": False,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def catalog_out(item: dict) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "description": item.get("description") or "",
        "instructions": item.get("instructions") or "",
        "emoji": item.get("emoji") or "🤖",
        "starters": list(item.get("starters") or [])[:4],
        "file_ids": [],
        "catalog": True,
        "mine": False,
        "pulse": bool(item.get("pulse")),
        "created_at": None,
        "updated_at": None,
    }


async def resolve_gpt(db: AsyncSession, user: User, gpt_id: str | None) -> dict | None:
    """Return a serialized GPT the user is allowed to run, or None."""
    if not gpt_id:
        return None
    cat = catalog_by_id(gpt_id)
    if cat:
        return catalog_out(cat)
    row = await db.get(CustomGpt, gpt_id)
    if not row or row.user_id != user.id:
        return None
    return gpt_out(row)


async def knowledge_blocks(db: AsyncSession, user: User, file_ids: list[str]) -> list[str]:
    """Pull extracted text from knowledge files the user actually owns."""
    blocks: list[str] = []
    for fid in file_ids[:12]:
        asset = await db.get(FileAsset, fid)
        if not asset or asset.user_id != user.id or not asset.extracted_text:
            continue
        blocks.append(
            f'<gpt-knowledge name="{asset.filename}" type="{asset.mime}">\n'
            f"{asset.extracted_text[:12_000]}\n</gpt-knowledge>"
        )
    return blocks


async def list_mine(db: AsyncSession, user: User) -> list[CustomGpt]:
    return (
        (
            await db.execute(
                select(CustomGpt)
                .where(CustomGpt.user_id == user.id)
                .order_by(CustomGpt.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
