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


def patient_login(coord, pid):
    email = f"voice-patient-{uuid.uuid4().hex}@example.com"
    # a patient login is created at registration; add one for an existing patient through a second registration
    created = coord.post("/api/v1/patients", headers=H, json={"name": "Voice Patient", "birth_year": 1948, "patient_account": {"email": email, "password": PASSWORD}})
    assert created.status_code == 201
    patient = TestClient(app)
    assert patient.post("/api/v1/auth/login", headers=H, json={"email": email, "password": PASSWORD}).status_code == 200
    return patient, created.json()["id"]


def upload(client, pid, key=None, mime="audio/webm;codecs=opus", body=AUDIO, **params):
    headers = {**H, "Content-Type": mime, **({"Idempotency-Key": key} if key else {})}
    return client.post(f"/api/v1/patients/{pid}/voice-notes", headers=headers, content=body, params=params)


def heard(text, language="hi", confidence=0.9):
    return ai.Transcript(text, language, confidence, "gemma", "gemma-3n-e4b-it")


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: None)
    monkeypatch.setattr(ai, "urgency_advisor", lambda: None)
    coord, _ = primary_contact_with_patient()
    patient, pid = patient_login(coord, "ignored")
    caretaker(coord, pid, "Water Helper")  # daily-help requests need someone to receive them, otherwise they go to the family
    return coord, patient, pid


def test_without_ai_the_note_is_kept_routed_for_a_person_and_playable(setup):
    coord, patient, pid = setup
    sent = upload(patient, pid)
    assert sent.status_code == 201
    body = sent.json()
    assert body["current_level"] == 2 and body["voice_note"]["status"] == "UNTRANSCRIBED" and body["voice_note"]["low_confidence"] is True
    assert body["title"] == "Voice note to review" and "listen" in body["safe_summary"]
    audio = coord.get(body["voice_note"]["audio_url"])
    assert audio.status_code == 200 and audio.content == AUDIO and audio.headers["cache-control"] == "no-store"
    listed = coord.get("/api/v1/incidents").json()["items"]
    assert next(i for i in listed if i["id"] == body["id"])["voice_note"]["audio_url"] == body["voice_note"]["audio_url"]
    outsider, _, _ = account("PRIMARY_CONTACT")
    assert outsider.get(body["voice_note"]["audio_url"]).status_code == 403


def test_transcript_is_routed_by_the_rules_and_shown_with_its_language(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I need water", "en", 0.95))
    body = upload(patient, pid).json()
    assert body["current_level"] == 1 and body["category"] == "DAILY_HELP"
    note = body["voice_note"]
    assert note["transcript"] == "I need water" and note["language"] == "en" and note["provider"] == "gemma" and note["low_confidence"] is False


def test_the_assistant_can_raise_the_level_but_never_lower_it(setup, monkeypatch):
    coord, patient, pid = setup
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I need water", "en"))
    monkeypatch.setattr(ai, "urgency_advisor", lambda: FakeAdvisor(4, "Said water but sounds unwell."))
    raised = upload(patient, pid).json()
    assert raised["current_level"] == 4 and raised["voice_note"]["applied_level"] == 4 and raised["voice_note"]["suggested_reason"] == "Said water but sounds unwell."
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: heard("I have chest pain", "en"))
    monkeypatch.setattr(ai, "urgency_advisor", lambda: FakeAdvisor(0, "Nothing urgent."))
    held = upload(patient, pid).json()
    assert held["current_level"] == 5 and held["voice_note"]["applied_level"] is None and held["voice_note"]["suggested_level"] == 0


def test_retries_do_not_transcribe_or_route_twice(setup, monkeypatch):
    coord, patient, pid = setup
    calls = []
    monkeypatch.setattr(ai, "transcribe_audio", lambda audio, mime, hint=None: calls.append(1) or heard("I need water", "en"))
    first = upload(patient, pid, key="voice-retry-1").json()
    second = upload(patient, pid, key="voice-retry-1").json()
    assert first["id"] == second["id"] and len(calls) == 1 and second["voice_note"]["id"] == first["voice_note"]["id"]


def test_recordings_are_validated_and_roles_respected(setup, monkeypatch):
    coord, patient, pid = setup
    assert upload(patient, pid, mime="text/plain").status_code == 415
    assert upload(patient, pid, body=b"tiny").status_code == 422
    monkeypatch.setattr(settings, "voice_max_bytes", 1500)
    assert upload(patient, pid).status_code == 413
    monkeypatch.setattr(settings, "voice_max_bytes", 3_000_000)
    assert TestClient(app).post(f"/api/v1/patients/{pid}/voice-notes", headers={**H, "Content-Type": "audio/webm"}, content=AUDIO).status_code == 401
    # a caretaker on the team reports for the patient; the note is flagged as sent on their behalf
    _, helper = caretaker(coord, pid, "Voice Helper")
    on_behalf = upload(helper, pid)
    assert on_behalf.status_code == 201 and on_behalf.json()["voice_note"]["status"] == "UNTRANSCRIBED"
    other, _, _ = account("CARETAKER")
    assert upload(other, pid).status_code == 403
