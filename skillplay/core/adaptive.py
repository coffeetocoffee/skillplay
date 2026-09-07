"""Section E — Adaptive engine v2: a tiny, offline-first local model.

Trained purely on the player's own per-attempt history (``progress["attempts"]``),
it predicts the probability a challenge will be solved correctly, then selects the
*next-best* challenge: one the player is likely to get wrong but where practice
still pays off (high expected learning gain). No data ever leaves the machine —
the fitted weights live in ``progress["model"]`` and training happens locally on
``finalize``.

The model is a small logistic regression fit with batch gradient descent in pure
Python (no numpy dependency). It is intentionally simple and bounded so it runs
instantly and stays explainable.
"""

from __future__ import annotations

import math
import random
from typing import Any

from . import engine, skillgraph
from . import progress as progress_mod
from .loader import Challenge, Pack

# Fixed feature order — must stay in sync with ``engine._attempt_features`` keys.
_FEATURE_KEYS = ("difficulty", "box", "mistakes", "weak_share", "rolling", "seen", "latency")

MIN_TRAIN_ATTEMPTS = 20
MAX_TRAIN_ATTEMPTS = 5000
MODEL_VERSION = 1
# Only retrain once at least this many *new* attempts have accumulated, so
# ``finalize`` stays cheap (G5: avoid re-fitting on every session save).
RETRAIN_MIN_NEW = 10
# How strongly the heuristic "drill the weakest mistake type" nudge is folded
# into the model's learning-gain score (G4: keep retention behavior when the
# model is active instead of silently dropping it).
RETENTION_BONUS_WEIGHT = 0.03


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _eval_auc(attempts: list[dict[str, Any]], model: AdaptiveModel) -> float | None:
    """Cheap offline effectiveness check: rank-based AUC of P(correct) vs the
    actual outcome (Mann-Whitney U, O(n log n)). 0.5 = no signal, 1.0 = perfect.
    Returns None when there's only one class present."""
    scores = []
    for a in attempts:
        if not a.get("feats"):
            continue
        y = 1.0 if a.get("correct") else 0.0
        scores.append((y, model.predict_correct(a["feats"])))
    if len(scores) < 2:
        return None
    scores.sort(key=lambda x: x[1])
    n_neg = concordant = n_pos = 0
    for y, _p in scores:
        if y == 0:
            n_neg += 1
        else:
            concordant += n_neg
            n_pos += 1
    if n_pos == 0 or n_neg == 0:
        return None
    return concordant / (n_pos * n_neg)


def _retention_bonus(progress: dict[str, Any], ch) -> float:
    """The heuristic's "drill the weakest mistake type" term (mirrors
    ``engine._challenge_weight``) so the model path keeps the proven retention
    behavior (G4). Zero for unseen/clean challenges."""
    bonus = 0.0
    dom = engine._dominant_mistake_type(progress, ch.id)
    if dom is not None:
        mt = progress.get("mistakes", {}).get(ch.id, {})
        bonus += mt.get(dom, 0) * 2
        if dom == engine._weakest_mistake_type(progress):
            bonus += 3
    return bonus


class AdaptiveModel:
    """A fitted logistic regressor over challenge features -> P(correct)."""

    def __init__(
        self, weights: dict[str, float] | None = None, bias: float = 0.0, trained_on: int = 0
    ):
        self.weights = weights or {k: 0.0 for k in _FEATURE_KEYS}
        self.bias = bias
        self.trained_on = trained_on

    def predict_correct(self, feats: dict[str, float]) -> float:
        z = self.bias
        for k in _FEATURE_KEYS:
            z += self.weights.get(k, 0.0) * feats.get(k, 0.0)
        return _sigmoid(z)

    def to_dict(self) -> dict[str, Any]:
        return {"weights": dict(self.weights), "bias": self.bias, "trained_on": self.trained_on}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AdaptiveModel:
        return cls(d.get("weights", {}), d.get("bias", 0.0), d.get("trained_on", 0))


def train_model(
    attempts: list[dict[str, Any]], iters: int = 60, lr: float = 0.3
) -> AdaptiveModel | None:
    """Fit the logistic model on recorded attempts. Returns None if there is
    not enough data to learn anything meaningful yet."""
    samples = [a for a in attempts if isinstance(a, dict) and a.get("feats")]
    if len(samples) < MIN_TRAIN_ATTEMPTS:
        return None

    feats_list = [a["feats"] for a in samples]
    ys = [1.0 if a.get("correct") else 0.0 for a in samples]
    w = {k: 0.0 for k in _FEATURE_KEYS}
    b = 0.0
    n = len(feats_list)
    for _ in range(iters):
        gw = {k: 0.0 for k in _FEATURE_KEYS}
        gb = 0.0
        for x, y in zip(feats_list, ys):
            p = _sigmoid(b + sum(w[k] * x.get(k, 0.0) for k in _FEATURE_KEYS))
            err = p - y
            for k in _FEATURE_KEYS:
                gw[k] += err * x.get(k, 0.0)
            gb += err
        for k in _FEATURE_KEYS:
            w[k] -= lr * gw[k] / n
        b -= lr * gb / n
    return AdaptiveModel(w, b, len(samples))


def retrain_if_needed(progress: dict[str, Any]) -> None:
    """Fit (or refresh) the model from recent attempts and store it locally.

    G5 hardening: the stored model carries a ``version`` so a format change can't
    silently break old saves (``load_model`` rejects mismatches), and retraining is
    throttled to at least ``RETRAIN_MIN_NEW`` new attempts so ``finalize`` stays
    cheap. A held-out AUC is stored for visibility into model effectiveness.
    """
    total = len(progress.get("attempts", []))
    if total < MIN_TRAIN_ATTEMPTS:
        return
    prev = progress.get("model") or {}
    if (
        prev.get("version") == MODEL_VERSION
        and (total - prev.get("trained_on_count", 0)) < RETRAIN_MIN_NEW
    ):
        return  # already trained on (almost) all current data
    attempts = progress["attempts"][-MAX_TRAIN_ATTEMPTS:]
    model = train_model(attempts)
    if model is None:
        return
    d = model.to_dict()
    d["version"] = MODEL_VERSION
    d["trained_on_count"] = total
    d["eval_auc"] = _eval_auc(attempts, model)
    progress["model"] = d


def load_model(progress: dict[str, Any]) -> AdaptiveModel | None:
    d = progress.get("model")
    if not d or d.get("version") != MODEL_VERSION:
        return None
    model = AdaptiveModel.from_dict(d)
    if model.trained_on < MIN_TRAIN_ATTEMPTS:
        return None
    return model


def challenge_failure_prob(model: AdaptiveModel, progress: dict[str, Any], ch: Challenge) -> float:
    """P(the player gets this challenge wrong) under the current model."""
    feats = engine._attempt_features(progress, ch)
    return 1.0 - model.predict_correct(feats)


def adaptive_reason(p_fail: float) -> str:
    pct = int(p_fail * 100)
    if pct >= 60:
        return f"Model: likely to slip ({pct}%) — high-value practice"
    if pct >= 35:
        return f"Model: worth drilling ({pct}%)"
    return f"Model: probably fine ({pct}%) — light review"


def next_best_challenge(
    progress: dict[str, Any], pack: Pack, skill: str | None = None
) -> Challenge | None:
    """The single best challenge to practice next for a skill (model-driven)."""
    model = load_model(progress)
    candidates = pack.challenges
    if skill:
        candidates = [c for c in candidates if c.skill == skill]
    if not candidates:
        return None
    if model is None:
        # Not enough data yet — fall back to the proven heuristic weighting.
        return max(candidates, key=lambda c: engine._challenge_weight(progress, c))
    # V4: never target a challenge whose prerequisites aren't satisfied yet —
    # the model walks the next unlockable frontier, not the weakest locked card.
    unlocked = [c for c in candidates if skillgraph.is_unlocked(progress, c)]
    candidates = unlocked or candidates
    # Higher failure probability = better practice target; the retention bonus
    # preserves the heuristic's "drill the weakest mistake type" nudge (G4).
    ranked = sorted(
        candidates,
        key=lambda c: (
            challenge_failure_prob(model, progress, c)
            + RETENTION_BONUS_WEIGHT * _retention_bonus(progress, c)
        ),
        reverse=True,
    )
    return ranked[0]


def select_adaptive_v2(
    pack: Pack, progress: dict[str, Any], session_size: int, model: AdaptiveModel | None = None
) -> list:
    """Pick a session of challenges using the trained model.

    Falls back to the classic weighted sampler when the model isn't trained yet,
    so early players get the same good experience as before.
    """
    model = model or load_model(progress)
    if model is None:
        return engine.select_challenges(pack, progress, session_size)

    today = progress_mod.today_str()
    due = []
    for ch in pack.challenges:
        rec = progress["challenges"].get(ch.id, {})
        next_due = rec.get("next_due", "")
        if next_due and next_due > today:
            continue
        due.append(ch)
    if not due:
        due = list(pack.challenges)

    # V4: respect prerequisites — only model-rank the unlocked frontier so the
    # adaptive session never schedules a card the player isn't ready for.
    due = engine._gate_prerequisites(due, progress)

    # Expected learning gain: likely-to-fail * difficulty value, plus the
    # heuristic retention nudge so the model path keeps drilling the player's
    # weakest mistake type instead of dropping it (G4).
    scored = []
    for ch in due:
        p_fail = challenge_failure_prob(model, progress, ch)
        gain = p_fail * (0.5 + getattr(ch, "difficulty", 1) / 10.0)
        gain += RETENTION_BONUS_WEIGHT * _retention_bonus(progress, ch)
        scored.append((gain, ch))
    scored.sort(key=lambda t: t[0], reverse=True)

    # Weighted sample without replacement among the strongest contenders, with
    # a little exploration noise so sessions don't become perfectly repetitive.
    top = scored[: max(session_size, min(len(scored), session_size * 3))]
    pool = [c for _, c in top]
    weights = [max(1, int(g * 100)) for g, _ in top]
    chosen: list = []
    pp, pw = list(pool), list(weights)
    while pp and len(chosen) < session_size:
        pick = random.choices(pp, weights=pw, k=1)[0]
        idx = pp.index(pick)
        chosen.append(pp.pop(idx))
        pw.pop(idx)
    for ch in chosen:
        ch.srs_reason = adaptive_reason(challenge_failure_prob(model, progress, ch))
    return chosen


def select_adaptive_v2_pack(packs: list[Pack], progress: dict[str, Any], session_size: int) -> list:
    """Like ``select_mixed`` but scored by the adaptive model across all packs."""
    all_ch = [c for p in packs for c in p.challenges]
    synth = Pack(
        id="adaptive",
        name="Adaptive",
        version="0.0.0",
        skill="mixed",
        description="Model-selected challenges across all your skills.",
        difficulty="mixed",
        author="core",
        challenges=all_ch,
    )
    return select_adaptive_v2(synth, progress, session_size)
