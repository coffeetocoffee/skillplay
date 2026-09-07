"""V3 — Half-life regression (HLR) scheduler (W4 latency-aware memory model).

Replaces the fixed Leitner box offsets with a learned per-card memory model.
Each card tracks a `half_life` (days): the time for predicted recall to drop to
50%. After every review we take one gradient step of half-life regression on the
binary recall outcome, using the elapsed delay since the last review and the
response latency (slow answers are treated as shakier recall). The next review is
then scheduled for when predicted recall is expected to fall to TARGET_RECALL.

This augments (not deletes) the existing `box` field: `box` is still updated for
backward-compatible weighting/display, but `next_due` is now driven by the HLR
prediction so spacing adapts to real retention instead of a fixed 0/1/3/7/16 map.

Pure + stdlib-only (matches the rest of the engine).
"""

from __future__ import annotations

import math
from datetime import date, timedelta

DEFAULT_HALF_LIFE = 2.5  # days, for a brand-new card
TARGET_RECALL = 0.90  # schedule the card when recall is predicted to drop to this
LEARN_RATE = 0.3  # HLR gradient step size per review
HESITANT_MS = 15_000  # W4: slower-than-this correct answers are shaky recall
MIN_HALF_LIFE = 0.25  # days (6h) — never schedule sooner than this
MAX_HALF_LIFE = 365.0  # days — cap stability so cards can't vanish for a year


def predict_recall(half_life_days: float, dt_days: float) -> float:
    """Probability of correct recall after `dt_days` since last review."""
    hl = half_life_days if half_life_days and half_life_days > 0 else DEFAULT_HALF_LIFE
    return 0.5 ** (max(0.0, dt_days) / hl)


def next_due_days(half_life_days: float, target: float = TARGET_RECALL) -> float:
    """Days until predicted recall falls to `target` (the review trigger)."""
    hl = max(
        MIN_HALF_LIFE,
        half_life_days if half_life_days and half_life_days > 0 else DEFAULT_HALF_LIFE,
    )
    # 0.5^(dt / hl) = target  ->  dt = hl * log2(1 / target)
    dt = hl * (math.log(1.0 / target) / math.log(2.0))
    return max(MIN_HALF_LIFE, min(dt, MAX_HALF_LIFE))


def next_due_iso(half_life_days: float, today: str | None = None) -> str:
    base = date.fromisoformat(today) if today else date.today()
    return (base + timedelta(days=next_due_days(half_life_days))).isoformat()


def update(
    half_life_days: float,
    dt_days: float,
    correct: bool,
    latency_ms: int | None = None,
) -> float:
    """One HLR gradient step: return the updated half-life (days).

    Increase stability when the card was recalled (especially after a long delay);
    decrease it on failure. A slow-but-correct answer is penalized slightly
    (hesitant recall) so durability, not just correctness, drives spacing."""
    hl = float(half_life_days) if half_life_days and half_life_days > 0 else DEFAULT_HALF_LIFE
    p = predict_recall(hl, dt_days)
    outcome = 1.0 if correct else 0.0
    err = outcome - p
    # Gradient of p wrt hl: dp/dhl = p * (ln2 * dt / hl^2)  (always positive).
    denom = p * (math.log(2.0) * max(dt_days, 1e-3) / (hl * hl))
    step = 0.0 if denom == 0 else LEARN_RATE * (err / denom)
    new_hl = hl + step
    if correct and latency_ms and latency_ms > HESITANT_MS:
        new_hl *= 0.8  # shaky recall -> shrink stability
    return max(MIN_HALF_LIFE, min(MAX_HALF_LIFE, new_hl))
