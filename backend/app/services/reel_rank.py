"""🏆 Reel ranking — the "For You" algorithm.

A reverse-chronological list is the difference between a demo and a product:
the newest upload always wins, a great reel is buried in an hour, and a creator
posting ten times in a row owns the whole feed. This module replaces that with
the scoring model short-video apps actually use.

The score has four parts, all deliberately explainable:

    score = engagement_velocity × time_decay × affinity × diversity_penalty

1. **Engagement velocity** — weighted interactions, not raw views. The weights
   encode intent: a share (I'll put my name on this) is worth far more than a
   view (the feed autoplayed it at me). Completion rate multiplies the whole
   term, because "watched to the end" is the strongest quality signal there is
   and it's the one metric that can't be farmed by posting more.

2. **Time decay** — a Hacker-News/Reddit-style gravity curve. Fresh content
   surfaces, but a reel with real engagement outranks a brand-new empty one for
   a while, which is exactly the behaviour a chronological feed can't produce.

3. **Affinity** — reels from creators you follow (or whose work you've liked
   before) get a boost, so following actually changes what you see.

4. **Diversity penalty** — the Nth consecutive reel from one author is damped,
   so a single prolific creator can't wall off the feed.

Everything is computed from columns already on the row, so ranking a page costs
one indexed scan. `hot_score` is cached on the row and refreshed lazily; the
viewer-specific terms (affinity, diversity) are applied in Python over the
candidate window, because they differ per viewer and can't be precomputed.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# ── weights ──────────────────────────────────────────────────────────────────
# Ordered by how much intent each action signals. A view is nearly free (the
# feed autoplayed it), a share is the strongest public endorsement there is.
W_VIEW = 0.05
W_LIKE = 1.0
W_COMMENT = 2.5
W_SAVE = 3.0
W_SHARE = 4.0
W_REPOST = 5.0

# Completion multiplies the engagement term rather than adding to it: a reel
# everybody finishes is categorically better than one with the same likes that
# nobody watches through. Range [1.0, 1 + COMPLETION_WEIGHT].
COMPLETION_WEIGHT = 2.0

# Gravity for the decay curve. 1.6 keeps a strong reel competitive for roughly
# a day; higher = more aggressively chronological.
GRAVITY = 1.6
DECAY_OFFSET_H = 2.0  # flattens the curve for the first couple of hours

# Affinity multipliers (viewer-specific).
FOLLOW_BOOST = 2.2      # you follow this creator
AFFINITY_BOOST = 1.35   # you've liked/saved this creator's work before
OWN_DAMP = 0.55         # your own reels shouldn't dominate your For You

# Diversity: the k-th consecutive reel by the same author is multiplied by
# AUTHOR_DAMP ** k, so one creator can't own the feed.
AUTHOR_DAMP = 0.55

# A brand-new reel has no signal yet; without a floor it would rank below an
# old reel with a single like and never get the impressions it needs to prove
# itself. This is the "exploration" term.
#
# Calibrated against the log-compressed engagement scale, NOT picked by feel:
# a strongly-performing reel (5k views / 800 likes / 200 shares, 90% completion)
# scores ~0.42 at 12 h and ~0.008 at 7 days. A floor of 0.25 therefore lets that
# reel out-rank fresh uploads for its first day, and retires it well inside a
# week — the window the tests pin down.
NEW_FLOOR = 0.25
NEW_GRACE_H = 6.0


def engagement_score(
    *,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    saves: int = 0,
    shares: int = 0,
    reposts: int = 0,
    completion: float = 0.0,
) -> float:
    """Weighted engagement, log-compressed, scaled by mean completion.

    The log is what stops the feed calcifying. Linear engagement means one
    runaway hit (50k views) outscores everything posted since by so much that
    no decay curve short of "ignore quality entirely" can retire it — the feed
    freezes around last week's winner. `log10` puts a 10× bigger audience only
    ~1 point ahead, so quality still sorts the feed but virality doesn't buy a
    permanent slot. (Same reason Reddit/HN compress their vote term.)

    `completion` is a 0..1 ratio; values outside that are clamped so a bad or
    hostile client report can't inflate a reel's score.
    """
    raw = (
        W_VIEW * max(0, views)
        + W_LIKE * max(0, likes)
        + W_COMMENT * max(0, comments)
        + W_SAVE * max(0, saves)
        + W_SHARE * max(0, shares)
        + W_REPOST * max(0, reposts)
    )
    c = min(1.0, max(0.0, completion))
    return math.log10(1.0 + raw) * (1.0 + COMPLETION_WEIGHT * c)


def time_decay(age_hours: float) -> float:
    """Gravity curve: 1/(age+offset)^GRAVITY, normalized so a fresh reel ≈ 1.0."""
    age = max(0.0, age_hours)
    return ((DECAY_OFFSET_H) / (age + DECAY_OFFSET_H)) ** GRAVITY


def hot_score(
    *,
    created_at: datetime | None,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    saves: int = 0,
    shares: int = 0,
    reposts: int = 0,
    completion: float = 0.0,
    now: datetime | None = None,
) -> float:
    """The viewer-independent part of the score, cached on the row.

    Kept separate from the personalized terms so it can be recomputed in bulk
    by a background pass without knowing who is going to read the feed.
    """
    now = now or datetime.now(timezone.utc)
    if created_at is None:
        age_h = 0.0
    else:
        ts = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        age_h = max(0.0, (now - ts).total_seconds() / 3600.0)

    eng = engagement_score(
        views=views, likes=likes, comments=comments,
        saves=saves, shares=shares, reposts=reposts, completion=completion,
    )
    # Exploration floor: brand-new reels start with enough score to earn a first
    # impression, fading out over NEW_GRACE_H.
    floor = NEW_FLOOR * max(0.0, 1.0 - age_h / NEW_GRACE_H)
    return (eng + floor) * time_decay(age_h)


def mean_completion(completion_sum: float, completion_n: int) -> float:
    """Mean completion rate from the denormalized pair, guarding /0."""
    if not completion_n:
        return 0.0
    return min(1.0, max(0.0, completion_sum / completion_n))


def personalize(
    base: float,
    *,
    is_following: bool = False,
    has_affinity: bool = False,
    is_own: bool = False,
) -> float:
    """Apply the viewer-specific multipliers to a cached `hot_score`."""
    score = base
    if is_following:
        score *= FOLLOW_BOOST
    elif has_affinity:
        score *= AFFINITY_BOOST
    if is_own:
        score *= OWN_DAMP
    return score


def diversify(scored: list[tuple[str, float, str]]) -> list[tuple[str, float, str]]:
    """Damp runs of the same author, then re-sort.

    `scored` is [(reel_id, score, author_id)] highest-first. Walking the list in
    order and damping by how many times an author has already appeared is the
    cheap, deterministic version of the "don't show me six clips from the same
    person" rule — no shuffling, so pagination stays stable.
    """
    seen: dict[str, int] = {}
    out: list[tuple[str, float, str]] = []
    for reel_id, score, author in scored:
        k = seen.get(author, 0)
        out.append((reel_id, score * (AUTHOR_DAMP ** k), author))
        seen[author] = k + 1
    out.sort(key=lambda t: t[1], reverse=True)
    return out
