"""Voice notes: record, preview (what was heard, in English too, and who will be told), then confirm and send.

Nothing reaches the care team until the sender has seen the preview and confirmed it. The audio is always kept and always
playable; the transcript, the translation and the routing suggestion are aids that the sender can correct.
"""
from __future__ import annotations

import logging
import unicodedata
import uuid
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.clock import now
from app.core.config import settings
from app.core.db import get_db
from app.models import Incident, Role, TeamRole, VoiceNote
from app.services import ai

log = logging.getLogger("second_patient")
from app.core.features import feature_required

router = APIRouter(prefix="/api/v1", tags=["voice notes"], dependencies=[Depends(feature_required("voice_notes"))])
MIN_BYTES = 800
ALLOWED = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac", "audio/x-m4a", "video/webm")
LOW_CONFIDENCE = 0.6
UNHEARD = "Voice note (not transcribed). Please listen to the recording."
DRAFT_LIFETIME = timedelta(days=1)
PREVIEW_LIMIT, PREVIEW_WINDOW = 12, 600  # recordings per person per ten minutes: they call paid or quota-limited AI services
preview_attempts: dict[str, deque[float]] = defaultdict(deque)
LEVEL_NAMES = ["For information", "Caretakers asked", "Family asked", "Healthcare team asked", "Doctor asked", "Emergency"]
ROLE_LABEL = {"CARETAKER": "Caretaker", "PRIMARY_CONTACT": "Family", "PROFESSIONAL": "Healthcare team"}


class SendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript: str | None = Field(default=None, max_length=1000)


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript: str = Field(max_length=1000)


class FixedAdvisor:
    """Reuses the suggestion already shown in the preview, so confirming the same text does not ask the model again."""

    def __init__(self, level, reason, provider):
        self.level, self.reason, self.provider, self.applied = level, reason, provider, None

    def advise(self, text, context):
        return self.level


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _clean(text: str | None) -> str:
    return "".join(ch for ch in (text or "") if unicodedata.category(ch)[0] != "C" or ch in "\n\t").strip()


def voice_summary(note: VoiceNote) -> dict:
    heard = note.status == "TRANSCRIBED"
    return {"id": note.id, "status": note.status, "transcript": note.transcript if heard else "", "english": note.english if heard else "", "edited": note.edited,
            "language": note.language, "confidence": note.confidence,
            "low_confidence": (not heard) or note.confidence is None or note.confidence < LOW_CONFIDENCE, "provider": note.stt_provider,
            "suggested_level": note.suggested_level, "suggested_reason": note.suggested_reason, "applied_level": note.applied_level,
            "audio_url": f"/api/v1/voice-notes/{note.id}/audio", "size_bytes": note.size_bytes}


def voice_notes_for(db: Session, incident_ids: list) -> dict:
    """Sent voice notes keyed by incident id, without loading the audio."""
    if not incident_ids: return {}
    rows = db.scalars(select(VoiceNote).where(VoiceNote.incident_id.in_(incident_ids), VoiceNote.is_draft.is_(False))).all()
    return {n.incident_id: voice_summary(n) for n in rows}


def _sender_checks(db: Session, user, patient_id: uuid.UUID):
    from app.main import patient_access
    patient, member = patient_access(db, user, patient_id)
    if user.role == Role.PATIENT:
        if not member or member.team_role != TeamRole.PATIENT_SELF: raise HTTPException(403, "Patient access denied")
    elif member is None:
        raise HTTPException(403, "Care team messages must be sent on behalf of the patient")
    return patient


def _routing(db: Session, patient, text: str, english: str | None):
    """Who would be told for this text, by the same rules the real request uses. Creates nothing."""
    from app.engine.escalation_classifier import classify_message
    from app.main import incident_recipients
    advisor = ai.urgency_advisor() if text else None
    basis = text or UNHEARD
    combined = basis if not english or english.strip() == basis else f"{basis}\n{english.strip()}"
    classification = classify_message(combined, context={"mobility_level": patient.mobility_level}, advisor=advisor)
    level = classification.level
    recipients = incident_recipients(db, patient.id, level)
    if level == 1 and not recipients:  # nobody to take a daily-help request: it goes to the family
        level = 2
        recipients = incident_recipients(db, patient.id, 2)
    applied = (classification.advisor or {}).get("applied_level")
    if advisor is not None: advisor.applied = applied
    groups: dict[str, list[str]] = {}
    for person in recipients: groups.setdefault(person.role.value, []).append(person.name)
    reason = (advisor.reason if advisor is not None and applied is not None and advisor.reason else None) or (classification.reasons[0] if classification.reasons else None)
    routing = {"level": level, "level_name": LEVEL_NAMES[level], "emergency": level >= 5, "no_recipients": not recipients, "reason": reason,
               "notify": [{"role": r, "label": ROLE_LABEL.get(r, r.title()), "names": sorted(names)} for r, names in groups.items()],
               "suggested_level": advisor.level if advisor is not None else None, "suggested_reason": advisor.reason if advisor is not None else None,
               "applied_level": applied, "assistant": advisor.provider if advisor is not None else None}
    return routing, advisor


def _store_routing(note: VoiceNote, routing: dict, advisor) -> None:
    note.suggested_level = routing["suggested_level"]
    note.suggested_reason = routing["suggested_reason"]
    note.advisor_provider = getattr(advisor, "provider", None) if advisor is not None else None
    note.applied_level = routing["applied_level"]


def _preview(note: VoiceNote, routing: dict) -> dict:
    heard = note.status == "TRANSCRIBED"
    return {**voice_summary(note), "id": note.id, "patient_id": note.patient_id, "heard": heard, "routing": routing,
            "transcript": note.transcript, "english": note.english,
            "needs_translation_check": bool(heard and note.language and not note.language.startswith("en") and not note.english)}


def _make_preview(db: Session, request: Request, user, patient_id: uuid.UUID, audio: bytes, mime: str, language_hint: str | None) -> dict:
    patient = _sender_checks(db, user, patient_id)
    attempts = preview_attempts[str(user.id)]
    cutoff = time.monotonic() - PREVIEW_WINDOW
    while attempts and attempts[0] < cutoff: attempts.popleft()
    if len(attempts) >= PREVIEW_LIMIT: raise HTTPException(429, "Too many voice notes in a short time. Please wait a few minutes, or type your message.", headers={"Retry-After": "60"})
    attempts.append(time.monotonic())
    db.execute(delete(VoiceNote).where(VoiceNote.is_draft.is_(True), VoiceNote.created_at < now() - DRAFT_LIFETIME))
    heard = ai.transcribe_audio(audio, mime, language_hint)
    text = _clean(heard.text)[:1000] if heard else ""
    english = ai.translate_to_english(text, heard.language if heard else language_hint) if text else None
    routing, advisor = _routing(db, patient, text, english)
    note = VoiceNote(patient_id=patient.id, sender_user_id=user.id, mime_type=mime[:60], size_bytes=len(audio), audio=audio, is_draft=True,
                     status="TRANSCRIBED" if text else "UNTRANSCRIBED", transcript=text, transcript_original=text, english=english or "",
                     language=heard.language if heard else None, confidence=heard.confidence if heard else None,
                     stt_provider=heard.provider if heard else None, stt_model=heard.model if heard else None)
    _store_routing(note, routing, advisor)
    db.add(note); db.commit()
    return _preview(note, routing)


def _own_draft(db: Session, user, note_id: uuid.UUID) -> VoiceNote:
    note = db.get(VoiceNote, note_id)
    if note is None or note.sender_user_id != user.id: raise HTTPException(404, "Voice note not found")
    return note


@router.post("/patients/{patient_id}/voice-notes/preview", status_code=201)
async def preview_voice_note(patient_id: uuid.UUID, request: Request, language: str | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Step 1. Body is the raw audio. Returns what was heard, its English translation and who would be told. Nothing is sent yet."""
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime not in ALLOWED: raise HTTPException(415, "Send the recording as audio (webm, ogg, mp4, mp3 or wav)")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.voice_max_bytes: raise HTTPException(413, "That recording is too long. Keep voice notes under a minute.")
    audio = await request.body()
    if len(audio) > settings.voice_max_bytes: raise HTTPException(413, "That recording is too long. Keep voice notes under a minute.")
    if len(audio) < MIN_BYTES: raise HTTPException(422, "That recording is too short to send")
    hint = language.strip().lower()[:8] if language and language.strip().isalpha() else None
    return await run_in_threadpool(_make_preview, db, request, user, patient_id, audio, request.headers.get("content-type", mime), hint)


@router.post("/voice-notes/{note_id}/check")
def check_voice_note(note_id: uuid.UUID, body: CheckIn, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Re-translate and re-route after the sender corrected the text. Still a preview: nothing is sent."""
    note = _own_draft(db, user, note_id)
    if not note.is_draft: raise HTTPException(409, "This voice note was already sent")
    patient = _sender_checks(db, user, note.patient_id)
    text = _clean(body.transcript)
    english = ai.translate_to_english(text, note.language) if text else None
    routing, advisor = _routing(db, patient, text, english)
    note.transcript, note.english = text, english or ""
    note.status = "TRANSCRIBED" if text else "UNTRANSCRIBED"
    _store_routing(note, routing, advisor)
    db.commit()
    return _preview(note, routing)


@router.post("/voice-notes/{note_id}/send", status_code=201)
def send_voice_note(note_id: uuid.UUID, request: Request, body: SendIn | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Step 2. The sender has seen the preview and confirms. Only now is a request created and the care team told."""
    from app.main import PatientMessageIn, create_message, incident_payload
    note = _own_draft(db, user, note_id)
    if not note.is_draft:  # a retried confirmation returns the request that was already created
        incident = db.get(Incident, note.incident_id) if note.incident_id else None
        if incident is None: raise HTTPException(409, "This voice note was already sent")
        return {**incident_payload(incident), "voice_note": voice_summary(note)}
    patient = _sender_checks(db, user, note.patient_id)
    text = _clean(body.transcript) if body is not None and body.transcript is not None else note.transcript
    english, advisor = note.english or None, None
    if text != note.transcript:  # corrected after the last preview: translate and route this text, not the old one
        english = ai.translate_to_english(text, note.language) if text else None
        routing, advisor = _routing(db, patient, text, english)
        _store_routing(note, routing, advisor)
    elif text and note.suggested_level is not None:
        advisor = FixedAdvisor(note.suggested_level, note.suggested_reason, note.advisor_provider)
    message = PatientMessageIn(body=text or UNHEARD, channel="VOICE", language_hint=note.language, on_behalf=user.role != Role.PATIENT)
    incident = create_message(note.patient_id, message, request, user, db, advisor=advisor, classify_extra=english)
    note.transcript, note.english = text, english or ""
    note.status = "TRANSCRIBED" if text else "UNTRANSCRIBED"
    note.edited = bool(note.transcript_original) and text != note.transcript_original
    note.incident_id, note.is_draft = incident["id"], False
    if advisor is not None and getattr(advisor, "applied", None) is not None: note.applied_level = advisor.applied
    db.commit()
    return {**incident, "voice_note": voice_summary(note)}


@router.delete("/voice-notes/{note_id}", status_code=204)
def discard_voice_note(note_id: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Throw away a recording that has not been sent."""
    note = _own_draft(db, user, note_id)
    if not note.is_draft: raise HTTPException(409, "A sent voice note cannot be removed")
    db.delete(note); db.commit()
    return Response(status_code=204)


@router.get("/voice-notes/{note_id}/audio")
def voice_note_audio(note_id: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    from app.main import may_read_incident, patient_access
    note = db.get(VoiceNote, note_id)
    if not note: raise HTTPException(404, "Voice note not found")
    if note.is_draft:
        if note.sender_user_id != user.id: raise HTTPException(404, "Voice note not found")
    else:
        _, member = patient_access(db, user, note.patient_id)
        incident = db.get(Incident, note.incident_id) if note.incident_id else None
        if incident is not None and not may_read_incident(db, incident, user, member): raise HTTPException(403, "Voice note access denied")
        if incident is None and note.sender_user_id != user.id: raise HTTPException(403, "Voice note access denied")
    return Response(content=note.audio, media_type=note.mime_type.split(";")[0], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
