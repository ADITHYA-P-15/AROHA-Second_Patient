"""Points the Backup Matcher adds for reputation and the patient's preferences (flag `team_builder`).

Defaults below; MATCHER_POLICY (a JSON object merged over them) overrides any value. Validated at start-up like
CHECKIN_POLICY and REPUTATION_POLICY. These points only reorder people who already pass every hard rule
(availability, overlaps, capabilities, limits, professional-only, already declined).
See docs/BACKUP_MATCHER.md for the table.
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache

DEFAULT_POLICY: dict = {
    "reputation_max": 10,      # composite 100 -> +10, 50 -> 0, 0 -> -10; unrated -> 0 (neutral, labelled)
    "reliability_max": 8,      # reliability record, same shape
    "same_city": 5,
    "same_sector": 2,          # only when the city does not match
    "language_match": 6,
    "need_covered": 4,         # team building: per support need of the patient the caretaker can help with
    "little_capacity": 5,      # team building: subtracted when already at their limits or with no free hours this week
}


class PolicyError(ValueError):
    pass


def validate(p: dict) -> dict:
    unknown = set(p) - set(DEFAULT_POLICY)
    if unknown: raise PolicyError(f"Unknown matcher policy keys: {', '.join(sorted(unknown))}")
    for key, value in p.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 40:
            raise PolicyError(f"{key} must be a whole number of points from 0 to 40")
    return p


def build(raw: str | None) -> dict:
    p = copy.deepcopy(DEFAULT_POLICY)
    if raw and raw.strip():
        try: override = json.loads(raw)
        except json.JSONDecodeError as exc: raise PolicyError(f"MATCHER_POLICY is not valid JSON: {exc.msg}") from None
        if not isinstance(override, dict): raise PolicyError("MATCHER_POLICY must be a JSON object")
        p.update(override)
    return validate(p)


@lru_cache(maxsize=1)
def _cached(raw: str) -> dict:
    return build(raw)


def policy() -> dict:
    from app.core.config import settings
    return copy.deepcopy(_cached(settings.matcher_policy or ""))
