"""Pure detection rules for time-sensitive activity acknowledgements and overdue tasks."""
from datetime import datetime, timedelta


def detect_task_incidents(activities: list[dict], now: datetime) -> list[dict]:
    found = []
    for item in activities:
        if item.get("lifecycle_status") != "SCHEDULED":
            continue
        if not item.get("primary_confirmed"):
            continue
        importance = item.get("importance", "MEDIUM")
        start = item["scheduled_start"]
        end = item["scheduled_end"]
        if start.tzinfo is None: start = start.replace(tzinfo=now.tzinfo)
        if end.tzinfo is None: end = end.replace(tzinfo=now.tzinfo)
        if item.get("acknowledged_at") is None and now <= start <= now + timedelta(minutes=30):
            found.append({"kind":"TASK_UNACKNOWLEDGED", "activity_id":item["id"], "patient_id":item["patient_id"],
                          "level":2 if importance in {"HIGH","CRITICAL"} else 1,
                          "dedupe_key":f"task:{item['id']}:TASK_UNACKNOWLEDGED"})
        if now > end + timedelta(minutes=15):
            found.append({"kind":"TASK_OVERDUE", "activity_id":item["id"], "patient_id":item["patient_id"],
                          "level":2 if importance in {"HIGH","CRITICAL"} else 1,
                          "dedupe_key":f"task:{item['id']}:TASK_OVERDUE"})
    return found
