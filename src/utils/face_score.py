from __future__ import annotations


DARK_CIRCLE_SCORE_MULTIPLIER = 10.0
DARK_CIRCLE_SCORE_MIN = 0.0
DARK_CIRCLE_SCORE_MAX = 100.0


def normalize_dark_circle_score(score):
    if score is None:
        return None
    normalized = float(score) * DARK_CIRCLE_SCORE_MULTIPLIER
    return max(DARK_CIRCLE_SCORE_MIN, min(DARK_CIRCLE_SCORE_MAX, normalized))
