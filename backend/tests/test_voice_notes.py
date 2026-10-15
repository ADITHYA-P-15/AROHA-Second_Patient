import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import ai
from tests.helpers import H, PASSWORD, account, caretaker, primary_contact_with_patient

AUDIO = b"RIFF" + b"\x00" * 2000


class FakeAdvisor:
    def __init__(self, level, reason="Because."):
        self.level, self.reason, self.provider, self.applied = level, reason, "groq", None

    def advise(self, text, context):
        return self.level


def patient_login(coord):
    email = f"voice-patient-{uuid.uuid4().hex}@example.com"
    created = coord.post("/api/v1/patients", headers=H, json={"name": "Voice Patient", "birth_year": 1948, "patient_account": {"email": email, "password": PASSWORD}})
    assert created.status_code == 201
    patient = TestClient(app)
    assert patient.post("/api/v1/auth/login", headers=H, json={"email": email, "password": PASSWORD}).status_code == 200
    return patient, created.json()["id"]


def preview(client, pid, mime="audio/webm;codecs=opus", body=AUDIO, **params):
    return client.post(f"/api/v1/patients/{pid}/voice-notes/preview", headers={**H, "Content-Type": mime}, content=body, params=params)


def send(client, note_id, transcript=None, key=None):
    headers = {**H, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"/api/v1/voice-notes/{note_id}/send", headers=headers, json={} if transcript is None else {"transcript": transcript})


def heard(text, language="hi", confidence=0.9):
    return ai.Transcript(text, language, confidence, "groq", "whisper-large-v3")


def incidents(client):
    return client.get("/api/v1/incidents").json()["items"]


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: None)
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: None)
    monkeypatch.setattr(ai, "urgency_advisor", lambda: None)
    coord, _ = primary_contact_with_patient()
    patient, pid = patient_login(coord)
    caretaker(coord, pid, "Water Helper")  # daily-help requests need someone to receive them, otherwise they go to the family
    return coord, patient, pid


def test_nothing_is_sent_until_the_preview_is_confirmed(setup):
    coord, patient, pid = setup
    before = len(incidents(coord))
    shown = preview(patient, pid)
    assert shown.status_code == 201
    body = shown.json()
    assert body["heard"] is False and body["routing"]["level"] == 2 and body["routing"]["notify"][0]["label"] == "Family"
    assert len(incidents(coord)) == before  # a preview creates no request and tells nobody
    sent = send(patient, body["id"])
    assert sent.status_code == 201
    result = sent.json()
    assert result["current_level"] == 2 and result["title"] == "Voice note to review" and result["voice_note"]["status"] == "UNTRANSCRIBED"
    assert len(incidents(coord)) == before + 1
    audio = coord.get(result["voice_note"]["audio_url"])
    assert audio.status_code == 200 and audio.content == AUDIO and audio.headers["cache-control"] == "no-store"
    outsider, _, _ = account("PRIMARY_CONTACT")
    assert outsider.get(result["voice_note"]["audio_url"]).status_code == 403


def test_preview_shows_the_spoken_text_the_english_and_who_will_be_told(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("mujhe paani chahiye", "hi"))
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: "I need water")
    body = preview(patient, pid).json()
    assert body["transcript"] == "mujhe paani chahiye" and body["english"] == "I need water" and body["language"] == "hi"
    assert body["routing"]["level"] == 1 and [n["label"] for n in body["routing"]["notify"]] == ["Caretaker"] and body["routing"]["notify"][0]["names"] == ["Water Helper"]
    sent = send(patient, body["id"]).json()
    assert sent["current_level"] == 1 and sent["voice_note"]["english"] == "I need water" and sent["voice_note"]["edited"] is False


def test_the_english_translation_catches_what_a_misheard_word_hides(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("ನನಗೆ ಎದೆ ನೋಗು ಇದೆ", "kn"))  # "pain" misspelled, so no keyword matches
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: "I have chest pain")
    body = preview(patient, pid).json()
    assert body["routing"]["level"] == 5 and body["routing"]["emergency"] is True
    assert send(patient, body["id"]).json()["current_level"] == 5


def test_a_corrected_transcript_is_checked_again_and_marked_edited(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I need water", "en"))
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: text)
    body = preview(patient, pid).json()
    assert body["routing"]["level"] == 1
    checked = patient.post(f"/api/v1/voice-notes/{body['id']}/check", headers=H, json={"transcript": "I have chest pain"}).json()
    assert checked["transcript"] == "I have chest pain" and checked["routing"]["level"] == 5
    sent = send(patient, body["id"], transcript="I have chest pain").json()
    assert sent["current_level"] == 5 and sent["voice_note"]["edited"] is True and sent["voice_note"]["transcript"] == "I have chest pain"


def test_the_assistant_can_raise_the_level_but_never_lower_it(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I need water", "en"))
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: text)
    monkeypatch.setattr(ai, "urgency_advisor", lambda: FakeAdvisor(4, "Said water but sounds unwell."))
    raised = preview(patient, pid).json()
    assert raised["routing"]["level"] == 4 and raised["routing"]["applied_level"] == 4 and raised["routing"]["reason"] == "Said water but sounds unwell."
    assert send(patient, raised["id"]).json()["current_level"] == 4
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I have chest pain", "en"))
    monkeypatch.setattr(ai, "urgency_advisor", lambda: FakeAdvisor(0, "Nothing urgent."))
    held = preview(patient, pid).json()
    assert held["routing"]["level"] == 5 and held["routing"]["applied_level"] is None
    assert send(patient, held["id"]).json()["current_level"] == 5


def test_drafts_are_private_and_can_be_discarded(setup):
    coord, patient, pid = setup
    draft = preview(patient, pid).json()
    assert coord.get(draft["audio_url"]).status_code == 404 and send(coord, draft["id"]).status_code == 404
    assert patient.get(draft["audio_url"]).status_code == 200
    assert patient.delete(f"/api/v1/voice-notes/{draft['id']}", headers=H).status_code == 204
    assert patient.get(draft["audio_url"]).status_code == 404 and send(patient, draft["id"]).status_code == 404


def test_confirming_twice_returns_the_same_request(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I need water", "en"))
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: text)
    draft = preview(patient, pid).json()
    first = send(patient, draft["id"], key="voice-confirm-1").json()
    second = send(patient, draft["id"], key="voice-confirm-1").json()
    assert first["id"] == second["id"]
    assert patient.delete(f"/api/v1/voice-notes/{draft['id']}", headers=H).status_code == 409


def test_recordings_are_validated_and_roles_respected(setup, monkeypatch):
    coord, patient, pid = setup
    assert preview(patient, pid, mime="text/plain").status_code == 415
    assert preview(patient, pid, body=b"tiny").status_code == 422
    monkeypatch.setattr(settings, "voice_max_bytes", 1500)
    assert preview(patient, pid).status_code == 413
    monkeypatch.setattr(settings, "voice_max_bytes", 3_000_000)
    assert TestClient(app).post(f"/api/v1/patients/{pid}/voice-notes/preview", headers={**H, "Content-Type": "audio/webm"}, content=AUDIO).status_code == 401
    _, helper = caretaker(coord, pid, "Voice Helper")
    on_behalf = preview(helper, pid)
    assert on_behalf.status_code == 201 and send(helper, on_behalf.json()["id"]).status_code == 201
    other, _, _ = account("CARETAKER")
    assert preview(other, pid).status_code == 403
    assert coord.post(f"/api/v1/voice-notes/{uuid.uuid4()}/send", headers=H, json={}).status_code == 404


def test_primary_contact_can_record_an_ambulance_call_and_the_team_is_told(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I have chest pain", "en"))
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: text)
    incident = send(patient, preview(patient, pid).json()["id"]).json()
    _, helper = caretaker(coord, pid, "Ambulance Helper")
    assert helper.post(f"/api/v1/incidents/{incident['id']}/ambulance", headers=H).status_code == 403  # only a primary contact
    assert patient.post(f"/api/v1/incidents/{incident['id']}/ambulance", headers=H).status_code == 403
    called = coord.post(f"/api/v1/incidents/{incident['id']}/ambulance", headers=H)
    assert called.status_code == 200 and called.json()["status"] == "recorded" and called.json()["notified"] >= 2
    again = coord.post(f"/api/v1/incidents/{incident['id']}/ambulance", headers=H)
    assert again.json()["status"] == "already_recorded"
    listed = next(i for i in incidents(coord) if i["id"] == incident["id"])
    assert listed["ambulance"]["by"] and listed["ambulance"]["at"]
    titles = [n["title"] for n in helper.get("/api/v1/notifications").json()["items"]]
    assert any(t.startswith("Ambulance being called for") for t in titles)
    assert patient.get("/api/v1/notifications").json()["items"]  # the patient is told too
    assert coord.post(f"/api/v1/incidents/{uuid.uuid4()}/ambulance", headers=H).status_code == 404


def test_demo_reset_removes_voice_notes_of_the_demo_patients(monkeypatch):
    from sqlalchemy import func, select
    from app.core.db import SessionLocal
    from app.main import seed
    from app.models import VoiceNote
    from app.services import demo
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: None)
    monkeypatch.setattr(ai, "translate_to_english", lambda text, language=None: None)
    monkeypatch.setattr(ai, "urgency_advisor", lambda: None)
    seed()
    anita = TestClient(app)
    assert anita.post("/api/v1/auth/login", headers=H, json={"email": "anita.iyer@secondpatient.demo", "password": settings.demo_password}).status_code == 200
    ramesh = TestClient(app)
    assert ramesh.post("/api/v1/auth/login", headers=H, json={"email": "ramesh.iyer@secondpatient.demo", "password": settings.demo_password}).status_code == 200
    pid = ramesh.get("/api/v1/patients").json()["items"][0]["id"]
    draft = preview(ramesh, pid).json()
    assert send(ramesh, draft["id"]).status_code == 201
    preview(ramesh, pid)  # and an unsent draft
    with SessionLocal() as db:
        ids = [p.id for p in demo.demo_patients(db).values()]
        assert db.scalar(select(func.count()).select_from(VoiceNote).where(VoiceNote.patient_id.in_(ids))) >= 2
    assert anita.post("/api/v1/demo/reset", headers=H).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(VoiceNote).where(VoiceNote.patient_id.in_(ids))) == 0
