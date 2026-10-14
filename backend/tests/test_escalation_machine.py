from datetime import datetime, timedelta, timezone

from app.engine.escalation_machine import DEFAULT_POLICY, auto_level_cap, deadline_minutes, next_action, validate_policy


def state(**overrides):
    data = {"status":"OPEN", "current_level":1, "severity":"MEDIUM", "category":"DAILY_HELP", "deadline_kind":"ACK", "created_at":datetime(2026,1,1,tzinfo=timezone.utc), "current_deadline_at":datetime(2026,1,1,0,10,tzinfo=timezone.utc), "acknowledged_at":None}
    return data | overrides


def test_ack_deadline_and_next_level():
    due = state()["current_deadline_at"]
    assert next_action(state(),DEFAULT_POLICY,due-timedelta(seconds=1)) is None
    action=next_action(state(),DEFAULT_POLICY,due)
    assert (action.kind,action.to_level,action.deadline_kind)==("AUTO_ESCALATED",2,"ACK")


def test_category_caps():
    assert auto_level_cap("DAILY_HELP")==3
    assert auto_level_cap("LOGISTICS","CRITICAL")==4
    assert auto_level_cap("HEALTH_CONCERN")==4
    state_at_cap=state(current_level=3,current_deadline_at=datetime(2026,1,1,tzinfo=timezone.utc))
    assert next_action(state_at_cap,DEFAULT_POLICY,state_at_cap["current_deadline_at"]).kind=="REMINDER_CAP"


def test_acknowledged_unresolved_escalates_and_l4_reminds():
    due=datetime(2026,1,1,tzinfo=timezone.utc)
    acknowledged=state(current_level=2,status="ACKNOWLEDGED",deadline_kind="RESOLVE",acknowledged_at=due-timedelta(minutes=1),current_deadline_at=due)
    assert next_action(acknowledged,DEFAULT_POLICY,due).reason=="Acknowledged but unresolved"
    doctor=state(current_level=4,category="HEALTH_CONCERN",current_deadline_at=due)
    assert next_action(doctor,DEFAULT_POLICY,due).kind=="REMINDER_DOCTOR"


def test_emergency_cadence_banner_and_acknowledged_reminder():
    created=datetime(2026,1,1,tzinfo=timezone.utc)
    due=created+timedelta(minutes=2)
    emergency=state(current_level=5,category="EMERGENCY",created_at=created,current_deadline_at=due)
    first=next_action(emergency,DEFAULT_POLICY,due)
    assert first.kind=="REMINDER_EMERGENCY"
    banner=next_action(emergency,DEFAULT_POLICY,created+timedelta(minutes=6))
    assert banner.kind=="UNACKNOWLEDGED_EMERGENCY" and banner.show_emergency_banner
    ack=state(current_level=5,category="EMERGENCY",status="ACKNOWLEDGED",acknowledged_at=due,current_deadline_at=due+timedelta(minutes=30),deadline_kind="RESOLVE")
    assert next_action(ack,DEFAULT_POLICY,ack["current_deadline_at"]).kind=="REMINDER_EMERGENCY"


def test_severity_multipliers_and_demo_scale():
    assert deadline_minutes(DEFAULT_POLICY,1,"ACK","HIGH")==5
    assert deadline_minutes(DEFAULT_POLICY,1,"ACK","LOW")==20
    assert deadline_minutes(DEFAULT_POLICY,1,"ACK","MEDIUM",0.1)==1
    assert deadline_minutes(DEFAULT_POLICY,1,"ACK","HIGH",0.1)==0.5


def test_terminal_incidents_never_advance():
    due=datetime.now(timezone.utc)
    for status in ("RESOLVED","CANCELLED"):
        assert next_action(state(status=status,current_deadline_at=due),DEFAULT_POLICY,due) is None


def test_policy_cannot_disable_five_minute_emergency_acknowledgement():
    policy = {**DEFAULT_POLICY, "ack_minutes": DEFAULT_POLICY["ack_minutes"].copy()}
    policy["ack_minutes"]["5"] = 6
    try:
        validate_policy(policy)
    except ValueError:
        return
    raise AssertionError("emergency acknowledgement cadence must remain at most five minutes")
