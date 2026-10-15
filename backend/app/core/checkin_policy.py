"""When a task needs a check-in, and when a check-in counts as late or missing.

Defaults below; CHECKIN_POLICY (a JSON object merged over them) overrides any of them. Validated at start-up, like
REPUTATION_POLICY, so a typo stops the app instead of silently changing when cover is searched for. See docs/CHECKIN.md.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache

CATEGORIES = ("APPOINTMENT", "TRANSPORT", "PRESCRIPTION", "MEDICATION", "FOLLOW_UP", "DAILY_ROUTINE", "MOBILITY", "LAB", "SUPPLIES", "POST_APPOINTMENT", "OTHER")
IMPORTANCE = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

DEFAULT_POLICY: dict = {
    # Tasks a caretaker checks in for. Medication doses are short and frequent, so they are confirmed by marking them done.
    "categories": ["APPOINTMENT", "TRANSPORT", "LAB", "DAILY_ROUTINE", "MOBILITY", "POST_APPOINTMENT"],
    "importance": ["MEDIUM", "HIGH", "CRITICAL"],
    "opens_before_min": 60,      # check-in is accepted from this long before the start
    "grace_min": 15,             # on time up to start + grace, late after
    "missing_after_min": 20,     # no check-in by start + this: the task is searched for cover (reason NO_CHECKIN)
}


class PolicyError(ValueError):
    pass


def validate(p: dict) -> dict:
    unknown = set(p) - set(DEFAULT_POLICY)
    if unknown: raise PolicyError(f"Unknown check-in policy keys: {', '.join(sorted(unknown))}")
    for key, allowed in (("categories", CATEGORIES), ("importance", IMPORTANCE)):
        if not isinstance(p[key], list) or not all(isinstance(x, str) and x in allowed for x in p[key]):
            raise PolicyError(f"{key} must be a list drawn from: {', '.join(allowed)}")
    for key in ("opens_before_min", "grace_min", "missing_after_min"):
        v = p[key]
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 720: raise PolicyError(f"{key} must be a whole number of minutes from 0 to 720")
    if p["missing_after_min"] < p["grace_min"]: raise PolicyError("missing_after_min cannot be shorter than grace_min")
    return p


def build(raw: str | None) -> dict:
    p = copy.deepcopy(DEFAULT_POLICY)
    if raw and raw.strip():
        try: override = json.loads(raw)
        except json.JSONDecodeError as exc: raise PolicyError(f"CHECKIN_POLICY is not valid JSON: {exc.msg}") from None
        if not isinstance(override, dict): raise PolicyError("CHECKIN_POLICY must be a JSON object")
        p.update(override)
    return validate(p)


@lru_cache(maxsize=1)
def _cached(raw: str) -> dict:
    return build(raw)


def policy() -> dict:
    from app.core.config import settings
    return copy.deepcopy(_cached(settings.checkin_policy or ""))


def requires_check_in(activity, p: dict | None = None) -> bool:
    p = p or policy()
    get = (lambda k: activity.get(k)) if isinstance(activity, dict) else (lambda k: getattr(activity, k, None))
    return bool(get("requires_caregiver")) and get("category") in p["categories"] and get("importance") in p["importance"]
