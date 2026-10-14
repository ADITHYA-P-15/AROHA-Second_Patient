from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine.availability import Window, effective_windows, is_available_for
from app.engine.workload import buffered_window, overlap, overlaps_for, workload

TZ = ZoneInfo("Asia/Kolkata")


def test_baseline_adjacent_windows_merge_and_exact_cover():
    d = datetime(2026, 10, 14, 9, tzinfo=TZ)
    caregiver = {"schedule": [{"weekday": d.weekday(), "start_min": 540, "end_min": 600}, {"weekday": d.weekday(), "start_min": 600, "end_min": 660}], "overrides": []}
    windows = effective_windows(caregiver, d, d + timedelta(hours=3))
    assert windows == [Window(d, d + timedelta(hours=2))]
    assert is_available_for(caregiver, Window(d, d + timedelta(hours=2))).available
    assert not is_available_for(caregiver, Window(d, d + timedelta(hours=2, minutes=1))).available


def test_unavailable_override_blocks_and_available_override_adds_time():
    d = datetime(2026, 10, 14, 9, tzinfo=TZ)
    caregiver = {"schedule": [], "overrides": [{"start_at": d, "end_at": d + timedelta(hours=2), "status": "AVAILABLE"}, {"start_at": d + timedelta(minutes=30), "end_at": d + timedelta(hours=1), "status": "UNAVAILABLE"}]}
    result = is_available_for(caregiver, Window(d, d + timedelta(hours=2)))
    assert not result.available and len(result.uncovered_segments) == 1 and len(result.blocking_overrides) == 1


def test_no_baseline_is_unavailable_and_touching_is_not_overlap():
    d = datetime(2026, 10, 14, 9, tzinfo=TZ)
    assert not is_available_for({"schedule": [], "overrides": []}, Window(d, d + timedelta(hours=1))).available
    assert not overlap(Window(d, d + timedelta(hours=1)), Window(d + timedelta(hours=1), d + timedelta(hours=2)))


def test_workload_counts_status_separately_and_excludes_backup():
    d = datetime(2026, 10, 14, 9, tzinfo=TZ)
    caregiver = "c1"
    rows = [({"caregiver_id": caregiver, "role": "PRIMARY", "status": "CONFIRMED"}, {"id": "a", "scheduled_start": d, "scheduled_end": d + timedelta(hours=1), "lifecycle_status": "SCHEDULED"}), ({"caregiver_id": caregiver, "role": "PRIMARY", "status": "PROPOSED"}, {"id": "b", "scheduled_start": d + timedelta(hours=2), "scheduled_end": d + timedelta(hours=3), "lifecycle_status": "SCHEDULED"}), ({"caregiver_id": caregiver, "role": "BACKUP", "status": "CONFIRMED"}, {"id": "c", "scheduled_start": d + timedelta(hours=4), "scheduled_end": d + timedelta(hours=5), "lifecycle_status": "SCHEDULED"})]
    result = workload(rows, caregiver)
    summary = result["by_day"][d.date().isoformat()]
    assert summary["confirmed"] == 1 and summary["pending"] == 1


def test_overnight_and_multi_day_availability_coverage():
    start = datetime(2026, 10, 14, 23, tzinfo=TZ)
    following = start.date() + timedelta(days=1)
    caregiver = {"schedule": [{"weekday": start.weekday(), "start_min": 1320, "end_min": 1440}, {"weekday": following.weekday(), "start_min": 0, "end_min": 120}], "overrides": []}
    assert is_available_for(caregiver, Window(start, start + timedelta(hours=2))).available
    assert is_available_for(caregiver, Window(start, start + timedelta(hours=25))).available is False


def test_buffers_apply_to_availability_and_patient_overlap():
    start = datetime(2026, 10, 14, 10, tzinfo=TZ)
    activity = {"id": "a", "scheduled_start": start, "scheduled_end": start + timedelta(hours=1), "buffer_before_min": 15, "buffer_after_min": 20, "lifecycle_status": "SCHEDULED"}
    assert buffered_window(activity) == Window(start-timedelta(minutes=15), start+timedelta(hours=1,minutes=20))
    other = {"id": "b", "scheduled_start": start + timedelta(hours=1), "scheduled_end": start + timedelta(hours=2), "lifecycle_status": "SCHEDULED"}
    assert overlaps_for(activity, [other]) == [other]
    other["scheduled_start"] = start + timedelta(hours=1, minutes=20)
    assert overlaps_for(activity, [other]) == []


def test_active_available_override_adds_to_empty_baseline():
    start = datetime(2026, 10, 14, 10, tzinfo=TZ)
    caregiver = {"schedule": [], "overrides": [{"start_at": start, "end_at": start + timedelta(hours=1), "status": "AVAILABLE"}]}
    assert is_available_for(caregiver, Window(start, start + timedelta(hours=1))).available
