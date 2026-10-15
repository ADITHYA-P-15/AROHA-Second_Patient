import uuid
from datetime import timedelta

import pytest

from app.core.clock import now
from app.core.db import SessionLocal
from app.models import CareActivity
from app.services import ai
from app.services import progress_report as pr
from tests.helpers import H, caretaker, join_as_professional, primary_contact_with_patient


def add_rx(pro, pid, medicine="Metformin", times=("08:00", "20:00")):
    start = (now() - timedelta(days=20)).date().isoformat()
    r = pro.post(f"/api/v1/patients/{pid}/prescriptions", headers=H, json={"medicine": medicine, "dose": "500 mg", "times": list(times), "start_date": start, "instructions": ""})
    assert r.status_code == 201, r.text
    return r.json()


def mark_doses(pid, rx, by, given_first, total_first, given_second, total_second):
    """Past dose outcomes: the generator only creates future doses, so earlier ones are written as the record would hold them."""
    with SessionLocal() as db:
        t = now()
        def make(days_ago, hour, given):
            due = (t - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0, microsecond=0)
            db.add(CareActivity(patient_id=uuid.UUID(pid), title="Metformin 500 mg", category="MEDICATION", scheduled_start=due, scheduled_end=due + timedelta(minutes=15),
                                importance="HIGH", requires_caregiver=True, lifecycle_status="COMPLETED" if given else "MISSED", completed_at=due if given else None,
                                created_by=uuid.UUID(by), source="PRESCRIPTION", source_id=uuid.UUID(rx["id"]), series_id=uuid.UUID(rx["id"])))
        for i in range(total_first): make(28 - i // 2, 8 if i % 2 == 0 else 20, i < given_first)
        for i in range(total_second): make(13 - i // 2, 8 if i % 2 == 0 else 20, i < given_second)
        db.commit()


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(ai, "complete_json", lambda system, user: None)
    coord, pid = primary_contact_with_patient()
    pro, _, pro_id = join_as_professional(coord, pid)
    rx = add_rx(pro, pid)
    mark_doses(pid, rx, pro_id, given_first=14, total_first=20, given_second=18, total_second=20)
    return coord, pro, pid


def facts_of(pro, pid, days=30):
    r = pro.get(f"/api/v1/patients/{pid}/progress-report?days={days}")
    assert r.status_code == 200, r.text
    return r.json()


def test_facts_come_from_the_record_and_the_default_report_is_a_draft(setup):
    coord, pro, pid = setup
    body = facts_of(pro, pid)
    texts = " ".join(f["text"] for f in body["facts"])
    assert body["status"] == "DRAFT" and body["reviewed"] is False and body["narrated_by"] == "template"
    assert "Metformin 500 mg, 2 times a day" in texts
    assert "70% in the first 15 days" in texts and "90% in the last 15 days" in texts and "rose" in texts
    assert "8 doses not recorded as given" in texts and "No check-ins were recorded" in texts  # no check-ins yet: said plainly
    assert body["summary"] and all(s["facts"] for s in body["summary"])
    assert any("first 15 days" in f["text"] for f in body["facts"])


def test_only_a_professional_on_the_team_can_read_it(setup):
    coord, pro, pid = setup
    assert coord.get(f"/api/v1/patients/{pid}/progress-report").status_code == 403
    other, _ = primary_contact_with_patient()
    stranger, _, _ = join_as_professional(other, other.get("/api/v1/patients").json()["items"][0]["id"])
    assert stranger.get(f"/api/v1/patients/{pid}/progress-report").status_code == 403
    assert pro.get(f"/api/v1/patients/{pid}/progress-report?days=3").status_code == 422


def test_ai_sentences_must_cite_facts_and_use_only_their_numbers(setup, monkeypatch):
    coord, pro, pid = setup
    shown = facts_of(pro, pid)["facts"]
    adherence = next(f for f in shown if f["key"] == "adherence")
    pct = 80  # 32 of 40 recorded doses
    assert "80% of recorded doses were given (32 of 40)" in adherence["text"]
    good = {"text": f"{pct}% of recorded doses were given.", "facts": [adherence["id"]]}
    invented = {"text": "Adherence reached 99% of doses.", "facts": [adherence["id"]]}
    uncited = {"text": "Doses were given.", "facts": []}
    unknown = {"text": "Doses were given.", "facts": ["F999"]}
    clinical = {"text": f"The patient is improving clinically with {pct}% given.", "facts": [adherence["id"]]}
    monkeypatch.setattr(ai, "complete_json", lambda system, user: ({"sentences": [good, invented, uncited, unknown, clinical]}, "groq"))
    r = pro.post(f"/api/v1/patients/{pid}/progress-report/draft", headers=H, json={"days": 30}).json()
    assert r["narrated_by"] == "ai" and r["provider"] == "groq"
    assert [s["text"] for s in r["summary"]] == [good["text"]] and r["dropped"] == 4


def test_when_every_sentence_is_rejected_the_report_falls_back_to_the_facts(setup, monkeypatch):
    coord, pro, pid = setup
    monkeypatch.setattr(ai, "complete_json", lambda system, user: ({"sentences": [{"text": "The patient is much better.", "facts": ["F1"]}]}, "gemma"))
    r = pro.post(f"/api/v1/patients/{pid}/progress-report/draft", headers=H, json={}).json()
    assert r["narrated_by"] == "template" and r["dropped"] == 1 and r["summary"]
    monkeypatch.setattr(ai, "complete_json", lambda system, user: (_ for _ in ()).throw(RuntimeError("down")))
    again = pro.post(f"/api/v1/patients/{pid}/progress-report/draft", headers=H, json={}).json()
    assert again["narrated_by"] == "template"


def test_check_ins_are_recorded_by_the_patient_or_family_and_appear_in_the_report(setup):
    coord, pro, pid = setup
    assert pro.post(f"/api/v1/patients/{pid}/check-ins", headers=H, json={"pain": 4}).status_code == 403
    assert coord.post(f"/api/v1/patients/{pid}/check-ins", headers=H, json={}).status_code == 422
    assert coord.post(f"/api/v1/patients/{pid}/check-ins", headers=H, json={"pain": 11}).status_code == 422
    assert coord.post(f"/api/v1/patients/{pid}/check-ins", headers=H, json={"pain": 6, "mood": 2, "note": "Slept badly"}).status_code == 201
    assert coord.post(f"/api/v1/patients/{pid}/check-ins", headers=H, json={"pain": 4, "mood": 3}).status_code == 201
    texts = [f["text"] for f in facts_of(pro, pid)["facts"] if f["section"] == "checkins"]
    assert any(t.startswith("2 check-ins") for t in texts)
    assert any("pain" in t and "5.0" in t for t in texts) and any("mood" in t and "2.5" in t for t in texts)
    assert len(pro.get(f"/api/v1/patients/{pid}/check-ins").json()["items"]) == 2


def test_validation_unit():
    facts = [{"id": "F1", "section": "adherence", "key": "adherence", "text": "70% of doses (14 of 20)."}, {"id": "F2", "section": "x", "key": "x", "text": "3 missed."}]
    by = {f["id"]: f for f in facts}
    assert pr._check({"text": "Doses given were 70%.", "facts": ["F1"]}, by)
    assert pr._check({"text": "70.0% were given, 3 missed.", "facts": ["F2", "F1"]}, by)["facts"] == ["F1", "F2"]
    assert pr._check({"text": "3 missed.", "facts": ["F1"]}, by) is None  # 3 is not in F1
    assert pr._check({"text": "No diagnosis.", "facts": ["F1"]}, by) is None
    assert pr._check({"text": "The patient is much better.", "facts": ["F1"]}, by) is None
    assert pr._check({"text": "Doses given improved a lot.", "facts": ["F1"]}, by) is None  # judgement without a figure
    assert pr._check({"text": "The patient improved, 70% given.", "facts": ["F1"]}, by) is None  # judgement about the person
    assert pr._check({"text": "Doses given improved to 70%.", "facts": ["F1"]}, by)
    assert pr._check({"text": "x" * 300, "facts": ["F1"]}, by) is None


def test_flag_off_hides_the_endpoints(setup, monkeypatch):
    from app.core.config import settings
    coord, pro, pid = setup
    monkeypatch.setattr(settings, "features", "voice_notes")
    assert pro.get(f"/api/v1/patients/{pid}/progress-report").status_code == 404
