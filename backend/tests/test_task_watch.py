from datetime import datetime, timedelta, timezone
from app.engine.task_watch import detect_task_incidents


def test_task_watch_ack_window_overdue_and_importance():
    now=datetime(2026,1,1,12,tzinfo=timezone.utc)
    base={"id":"activity-1","patient_id":"patient-1","lifecycle_status":"SCHEDULED","primary_confirmed":True,"importance":"MEDIUM","acknowledged_at":None,"scheduled_start":now+timedelta(minutes=20),"scheduled_end":now+timedelta(hours=1)}
    found=detect_task_incidents([base],now)
    assert len(found)==1 and found[0]["kind"]=="TASK_UNACKNOWLEDGED" and found[0]["level"]==1
    critical=base|{"id":"activity-2","importance":"CRITICAL"}
    assert detect_task_incidents([critical],now)[0]["level"]==2
    overdue=base|{"id":"activity-3","scheduled_start":now-timedelta(hours=1),"scheduled_end":now-timedelta(minutes=16)}
    assert detect_task_incidents([overdue],now)[0]["kind"]=="TASK_OVERDUE"


def test_task_watch_ignores_unconfirmed_completed_and_acknowledged():
    now=datetime(2026,1,1,12,tzinfo=timezone.utc)
    item={"id":"a","patient_id":"p","lifecycle_status":"SCHEDULED","primary_confirmed":False,"importance":"HIGH","acknowledged_at":None,"scheduled_start":now+timedelta(minutes=2),"scheduled_end":now+timedelta(minutes=3)}
    assert detect_task_incidents([item],now)==[]
    item["primary_confirmed"]=True;item["lifecycle_status"]="COMPLETED"
    assert detect_task_incidents([item],now)==[]
