"""Fictional check-in history for the demo's past tasks, so reliability records show on-time, late and missing check-ins.

Written once (per CHECKINS_VERSION) for past synthetic tasks that needed a check-in: mostly on time, some late, some missing.
"""
from __future__ import annotations

import random
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.checkin_policy import policy as current_policy
from app.core.clock import now
from app.models import AppSetting, CareActivity, CareAssignment, Caregiver, TaskCheckIn

CHECKINS_KEY = "demo_checkins"
CHECKINS_VERSION = 1


def ensure(db: Session) -> int:
    setting = db.get(AppSetting, CHECKINS_KEY)
    if setting is not None and (setting.value or {}).get("version") == CHECKINS_VERSION: return 0
    if db.get(AppSetting, "demo_population") is None: return 0  # wait for the background population, so its history is covered too
    p, at = current_policy(), now()
    rows = db.execute(select(CareActivity, CareAssignment.caregiver_id, Caregiver.user_id).join(CareAssignment, CareAssignment.activity_id == CareActivity.id)
                      .join(Caregiver, Caregiver.id == CareAssignment.caregiver_id)
                      .where(CareActivity.is_synthetic.is_(True), CareActivity.lifecycle_status.in_(("COMPLETED", "MISSED")), CareActivity.scheduled_start < at,
                             CareActivity.requires_caregiver.is_(True), CareActivity.category.in_(p["categories"]), CareActivity.importance.in_(p["importance"]),
                             CareAssignment.role == "PRIMARY", CareAssignment.status == "CONFIRMED").order_by(CareActivity.scheduled_start, CareActivity.id)).all()
    if not rows: return 0  # the population is built in the background; try again once it exists
    have = set(db.scalars(select(TaskCheckIn.activity_id)))
    rng = random.Random(20261019)
    written = 0
    for activity, caregiver_id, user_id in rows:
        roll = rng.random()
        if activity.id in have or activity.lifecycle_status == "MISSED" or roll >= 0.92: continue  # about 1 in 12 has no check-in
        late = roll >= 0.78
        minutes = rng.randint(p["grace_min"] + 1, p["grace_min"] + 40) if late else -rng.randint(0, 20)
        start = activity.scheduled_start
        db.add(TaskCheckIn(activity_id=activity.id, caregiver_id=caregiver_id, user_id=user_id, checked_in_at=start + timedelta(minutes=minutes),
                           status="LATE" if late else "ON_TIME", minutes_late=max(0, minutes) if late else 0, is_synthetic=True))
        written += 1
    value = {"version": CHECKINS_VERSION, "check_ins": written}
    if setting is None: db.add(AppSetting(key=CHECKINS_KEY, value=value))
    else: setting.value = value
    db.flush()
    return written
