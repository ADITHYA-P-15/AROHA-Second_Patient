"""Every number that shapes a caretaker's reputation, in one place.

Defaults below; a deployment overrides any of them with REPUTATION_POLICY (a JSON object merged over the defaults, one level
deep for the nested tables). The result is validated when the app starts, so a typo stops start-up instead of silently
changing how people are ranked. See docs/REPUTATION.md for the formulas these values feed.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache

DEFAULT_POLICY: dict = {
    # Composite: relative weight of each source. Missing sources are left out and the rest renormalised.
    "weights": {"metric": 40, "doctors": 25, "customers": 20, "agency": 15},
    # A patient's own review counts for this fraction of a primary contact's review.
    "patient_review_weight": 0.5,
    # Small samples are pulled toward the sector mean as if this many average ratings had already been given.
    "shrinkage_k": 3,
    # Below this many reviews plus doctor ratings, the profile says "not enough history yet" (the composite is still shown when it exists).
    "min_ratings_for_history": 3,
    # Reviewing: the reviewer's patient must have had this many completed tasks from the caretaker.
    "min_completed_tasks": 5,
    "rating_window_days": 90,      # one review / doctor rating per author per caretaker in this window
    "edit_window_days": 7,         # the author may edit for this long
    "prompt_repeat_days": 90,      # the "Rate <caretaker>" item re-appears at most once in this window
    "max_ratings_per_day": 10,     # abuse limit: new reviews and doctor ratings per author per day
    "max_reports_per_day": 10,     # abuse limit: reports per person per day
    # Metric score (our own records), rolling window.
    "metric_window_days": 90,
    "metric_min_tasks": 5,          # fewer decided tasks than this: no metric score yet
    "metric_components": {"on_time_completion": 45, "no_missed": 30, "on_time_check_in": 15, "cover_acceptance": 10},
    "check_in_grace_minutes": 15,   # a check-in later than the task start plus this is late
}

SOURCES = ("metric", "doctors", "customers", "agency")
COMPONENTS = ("on_time_completion", "no_missed", "on_time_check_in", "cover_acceptance")
_INTS = ("shrinkage_k", "min_ratings_for_history", "min_completed_tasks", "rating_window_days", "edit_window_days", "prompt_repeat_days",
         "max_ratings_per_day", "max_reports_per_day", "metric_window_days", "metric_min_tasks", "check_in_grace_minutes")


class PolicyError(ValueError):
    pass


def _weights(table, names, label):
    if not isinstance(table, dict) or set(table) != set(names):
        raise PolicyError(f"{label} must have exactly these keys: {', '.join(names)}")
    for key, value in table.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise PolicyError(f"{label}.{key} must be a number of zero or more")
    if sum(table.values()) <= 0:
        raise PolicyError(f"{label} must not all be zero")


def validate(policy: dict) -> dict:
    unknown = set(policy) - set(DEFAULT_POLICY)
    if unknown: raise PolicyError(f"Unknown reputation policy keys: {', '.join(sorted(unknown))}")
    _weights(policy["weights"], SOURCES, "weights")
    _weights(policy["metric_components"], COMPONENTS, "metric_components")
    w = policy["patient_review_weight"]
    if isinstance(w, bool) or not isinstance(w, (int, float)) or not 0 <= w <= 1:
        raise PolicyError("patient_review_weight must be between 0 and 1")
    for key in _INTS:
        value = policy[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < (0 if key in ("shrinkage_k", "check_in_grace_minutes") else 1) or value > 3650:
            raise PolicyError(f"{key} must be a whole number in range")
    if policy["edit_window_days"] > policy["rating_window_days"]:
        raise PolicyError("edit_window_days cannot exceed rating_window_days")
    return policy


def build(raw: str | None) -> dict:
    policy = copy.deepcopy(DEFAULT_POLICY)
    if raw and raw.strip():
        try: override = json.loads(raw)
        except json.JSONDecodeError as exc: raise PolicyError(f"REPUTATION_POLICY is not valid JSON: {exc.msg}") from None
        if not isinstance(override, dict): raise PolicyError("REPUTATION_POLICY must be a JSON object")
        for key, value in override.items():
            if key in ("weights", "metric_components") and isinstance(value, dict) and isinstance(policy.get(key), dict):
                policy[key] = {**policy[key], **value}
            else:
                policy[key] = value
    return validate(policy)


@lru_cache(maxsize=1)
def _cached(raw: str) -> dict:
    return build(raw)


def policy() -> dict:
    from app.core.config import settings
    return copy.deepcopy(_cached(settings.reputation_policy or ""))
