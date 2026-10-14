from datetime import UTC, date, datetime, timedelta

from app.engine.attention import evaluate_attention
from app.engine.daily_plan import build_daily_plan


def test_attention_is_deterministic_and_finds_missing_coverage():
    at = datetime(2026, 10, 14, 6, tzinfo=UTC)
    snapshot = {"activities": [{"id": "task-1", "title": "Pickup", "scheduled_start": at + timedelta(hours=2), "deadline": None, "importance": "MEDIUM", "requires_caregiver": True, "lifecycle_status": "SCHEDULED"}], "assignments": []}
    first = evaluate_attention(snapshot, at)
    assert [item.kind for item in first] == ["UNASSIGNED_REQUIRED"]
    assert first == evaluate_attention(snapshot, at)
    assert first[0].activity_ids == ("task-1",)


def test_attention_reports_confirmed_backup_gap_as_low_planning_reminder():
    at = datetime(2026, 10, 14, 6, tzinfo=UTC)
    activity = {"id": "task-1", "title": "Visit", "scheduled_start": at + timedelta(days=1), "importance": "HIGH", "requires_caregiver": True, "lifecycle_status": "SCHEDULED"}
    snapshot = {"activities": [activity], "assignments": [{"activity_id": "task-1", "caregiver_id": "cg-1", "role": "PRIMARY", "status": "CONFIRMED", "caregiver_available": True}]}
    result = evaluate_attention(snapshot, at)
    assert len(result) == 1
    assert result[0].kind == "NO_BACKUP_CRITICAL"
    assert result[0].severity == "LOW"


def test_attention_assignment_and_acknowledgement_time_boundaries():
    at = datetime(2026, 10, 14, 6, tzinfo=UTC)
    def evaluate(hours, assigned_at):
        activity = {"id": "a", "title": "Visit", "scheduled_start": at + timedelta(hours=hours), "importance": "MEDIUM", "requires_caregiver": True, "lifecycle_status": "SCHEDULED"}
        assignment = {"id": "as", "activity_id": "a", "role": "PRIMARY", "status": "AWAITING_CONFIRMATION", "assigned_at": assigned_at}
        return {item.kind for item in evaluate_attention({"activities": [activity], "assignments": [assignment]}, at)}
    assert "ASSIGNMENT_UNCONFIRMED" in evaluate(11, at)
    assert "ASSIGNMENT_UNCONFIRMED" not in evaluate(12, at)
    assert "ASSIGNMENT_UNCONFIRMED" not in evaluate(13, at - timedelta(hours=4))
    assert "ASSIGNMENT_UNCONFIRMED" in evaluate(13, at - timedelta(hours=4, seconds=1))

    for minutes, expected in ((29, True), (30, False), (31, False)):
        activity = {"id": "ack", "title": "Medication", "scheduled_start": at + timedelta(minutes=minutes), "importance": "MEDIUM", "requires_caregiver": True, "lifecycle_status": "SCHEDULED"}
        assignment = {"activity_id": "ack", "role": "PRIMARY", "status": "CONFIRMED"}
        kinds = {item.kind for item in evaluate_attention({"activities": [activity], "assignments": [assignment]}, at)}
        assert ("TASK_UNACKNOWLEDGED" in kinds) is expected


def test_daily_plan_uses_local_daypart_and_batches_routine_tasks():
    at = datetime(2026, 10, 14, 3, tzinfo=UTC)
    activities = [
        {"id": f"a{i}", "title": f"Medication {i}", "category": "MEDICATION", "series_id": "series", "scheduled_start": at + timedelta(minutes=30 * i), "scheduled_end": at + timedelta(minutes=30 * i + 15), "lifecycle_status": "SCHEDULED", "importance": "MEDIUM"}
        for i in (0, 1)
    ]
    assignments = [{"activity_id": row["id"], "caregiver_id": "cg-1", "caregiver_name": "Savitha", "role": "PRIMARY", "status": "CONFIRMED"} for row in activities]
    plan = build_daily_plan(activities, assignments, now=at, day=date(2026, 10, 14), timezone_name="Asia/Kolkata")
    assert len(plan["blocks"]) == 1
    assert plan["blocks"][0]["daypart"] == "Morning"
    assert len(plan["blocks"][0]["activities"]) == 2



def test_deadline_reason_uses_app_timezone():
    from datetime import UTC, datetime, timedelta
    from app.engine.attention import evaluate_attention
    now = datetime(2026, 10, 14, 0, 0, tzinfo=UTC)
    activity = {"id": "a1", "title": "Pickup", "importance": "MEDIUM", "requires_caregiver": False, "lifecycle_status": "SCHEDULED",
                "scheduled_start": now + timedelta(hours=8), "scheduled_end": now + timedelta(hours=9), "deadline": now + timedelta(hours=6)}
    items = evaluate_attention({"activities": [activity]}, now)
    deadline = next(x for x in items if x.kind == "DEADLINE_APPROACHING")
    assert "11:30" in deadline.reason  # 06:00 UTC shown in Asia/Kolkata
