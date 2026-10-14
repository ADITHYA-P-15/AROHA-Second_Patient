import uuid
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.clock import now
from app.core.config import settings
from app.main import app, seed
from tests.helpers import caretaker

H = {"X-Requested-With": "second-patient"}


def register_patient(c, name="Phase 2 patient"):
    suffix = uuid.uuid4().hex
    email = f"p2-{suffix}@example.com"
    assert c.post("/api/v1/auth/register", headers=H, json={"name":"P2 coordinator","email":email,"password":"SafePass!123"}).status_code == 201
    patient = c.post("/api/v1/patients", headers=H, json={"name":name,"birth_year":1950,"clinical_notes":"Private"})
    assert patient.status_code == 201
    return patient.json()["id"]


def future_times(days=1):
    zone = ZoneInfo("Asia/Kolkata")
    start = now().astimezone(zone) + timedelta(days=days)
    start = start.replace(hour=10, minute=0, second=0, microsecond=0)
    return start.isoformat(), (start + timedelta(hours=1)).isoformat()


def test_phase2_profile_caregiver_schedule_activity_warning_and_assignment_flow(monkeypatch):
    import app.api.domain as domain
    calls=[]
    monkeypatch.setattr(domain,"reassess",lambda session,patients,trigger,context=None:calls.append((tuple(patients),trigger)))
    c=TestClient(app); pid=register_patient(c)
    assert c.get(f"/api/v1/patients/{pid}").json()["my_permissions"] == ["plan:read","plan:manage","network:manage"]
    cid,_=caretaker(c,pid,"Limited caregiver",caps=())
    day=(now().astimezone(ZoneInfo("Asia/Kolkata")).date()+timedelta(days=1)).weekday()
    assert c.put(f"/api/v1/caregivers/{cid}/schedule",headers=H,json={"windows":[{"weekday":day,"start_min":0,"end_min":1440}]}).status_code==200
    start,end=future_times()
    created=c.post(f"/api/v1/patients/{pid}/activities",headers=H,json={"title":"Transport","category":"TRANSPORT","scheduled_start":start,"scheduled_end":end,"required_support":["TRANSPORT"]})
    assert created.status_code==201; aid=created.json()["id"]
    assigned=c.post(f"/api/v1/activities/{aid}/assignments",headers=H,json={"caregiver_id":cid,"role":"PRIMARY"})
    assert assigned.status_code==201 and any(w["code"]=="CAPABILITY_MISMATCH" for w in assigned.json()["warnings"])
    asid=assigned.json()["id"]
    assert c.post(f"/api/v1/assignments/{asid}/request-confirmation",headers=H,json={}).json()["status"]=="AWAITING_CONFIRMATION"
    assert c.post(f"/api/v1/assignments/{asid}/confirm",headers=H,json={}).json()["status"]=="CONFIRMED"
    assert any(trigger==domain.TriggerEvent.ASSIGNMENT_ADDED for _,trigger in calls)
    assert c.get(f"/api/v1/patients/{pid}/overview").status_code==200


def test_idor_househelp_clinical_privacy_and_role_confirmation():
    seed()
    anita=TestClient(app); assert anita.post("/api/v1/auth/login",headers=H,json={"email":"anita.iyer@secondpatient.demo","password":settings.demo_password}).status_code==200
    patients=anita.get("/api/v1/patients").json()["items"]; ramesh=next(x for x in patients if x["name"]=="Ramesh Iyer"); pid=ramesh["id"]
    outsider=TestClient(app); outsider.post("/api/v1/auth/register",headers=H,json={"name":"Outsider","email":f"outsider-{uuid.uuid4().hex}@test.com","password":"SafePass!123"})
    assert outsider.get(f"/api/v1/patients/{pid}").status_code==403
    savitha=TestClient(app); assert savitha.post("/api/v1/auth/login",headers=H,json={"email":"savitha@secondpatient.demo","password":settings.demo_password}).status_code==200
    assert savitha.get(f"/api/v1/patients/{pid}").json()["clinical_notes"] is None
    caregiver=next(x for x in savitha.get(f"/api/v1/patients/{pid}/caregivers").json()["items"] if x["name"]=="Savitha")
    start,end=future_times(8)
    activity=anita.post(f"/api/v1/patients/{pid}/activities",headers=H,json={"title":"Caregiver confirmation flow","category":"MEDICATION","scheduled_start":start,"scheduled_end":end,"required_support":["MEDICATION_ASSIST"]}).json()
    assignment=anita.post(f"/api/v1/activities/{activity['id']}/assignments",headers=H,json={"caregiver_id":caregiver["id"],"role":"PRIMARY"})
    assert assignment.status_code==201
    assert anita.post(f"/api/v1/assignments/{assignment.json()['id']}/request-confirmation",headers=H,json={}).status_code==200
    assert savitha.post(f"/api/v1/assignments/{assignment.json()['id']}/confirm",headers=H,json={}).json()["status"]=="CONFIRMED"


def test_schedule_validation_and_90_day_range():
    c=TestClient(app); pid=register_patient(c)
    cg={"id":caretaker(c,pid,"Scheduler",caps=())[0]}
    bad=c.put(f"/api/v1/caregivers/{cg['id']}/schedule",headers=H,json={"windows":[{"weekday":1,"start_min":500,"end_min":700},{"weekday":1,"start_min":600,"end_min":800}]})
    assert bad.status_code==422
    start=(now()+timedelta(days=1)).isoformat(); end=(now()+timedelta(days=92)).isoformat()
    assert c.get(f"/api/v1/caregivers/{cg['id']}/availability",params={"from":start,"to":end}).status_code==422


def test_series_generation_and_dependency_cycles():
    c=TestClient(app); pid=register_patient(c)
    start,end=future_times()
    series=c.post(f"/api/v1/patients/{pid}/activities/series",headers=H,json={"title":"Series","category":"DAILY_ROUTINE","scheduled_start":start,"scheduled_end":end,"requires_caregiver":False,"required_support":[],"recurrence":"DAILY","interval":1,"count":3})
    assert series.status_code==201 and len(series.json()["items"])==3
    activities=[]
    for i in range(3):
        begin,finish=future_times(10+i)
        item=c.post(f"/api/v1/patients/{pid}/activities",headers=H,json={"title":f"Dependency {i}","category":"OTHER","scheduled_start":begin,"scheduled_end":finish,"requires_caregiver":False,"required_support":[]})
        activities.append(item.json()["id"])
    assert c.post(f"/api/v1/activities/{activities[0]}/dependencies",headers=H,json={"depends_on_activity_id":activities[1]}).status_code==201
    assert c.post(f"/api/v1/activities/{activities[1]}/dependencies",headers=H,json={"depends_on_activity_id":activities[2]}).status_code==201
    cycle=c.post(f"/api/v1/activities/{activities[2]}/dependencies",headers=H,json={"depends_on_activity_id":activities[0]})
    assert cycle.status_code==409 and "cycle" in cycle.json()["error"]["message"].lower()
