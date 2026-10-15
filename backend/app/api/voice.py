"""Voice notes: record, transcribe (Gemma, Groq as fallback), route like any message, and play back to the care team.

The audio is always kept and always playable: the transcript and the assistant's suggestion are aids, never the only record.
"""
from __future__ import annotations

import logging
import unicodedata
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import get_db
from app.models import Incident, PatientMessage, VoiceNote
from app.services import ai

log = logging.getLogger("second_patient")
router = APIRouter(prefix="/api/v1", tags=["voice notes"])
MIN_BYTES = 800
ALLOWED = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac", "audio/x-m4a", "video/webm")
LOW_CONFIDENCE = 0.6
UNHEARD = "Voice note (not transcribed). Please listen to the recording."


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def voice_summary(note: VoiceNote) -> dict:
    heard = note.status == "TRANSCRIBED"
    return {"id": note.id, "status": note.status, "transcript": note.transcript if heard else "", "language": note.language, "confidence": note.confidence,
            "low_confidence": (not heard) or note.confidence is None or note.confidence < LOW_CONFIDENCE, "provider": note.stt_provider,
            "suggested_level": note.suggested_level, "suggested_reason": note.suggested_reason, "applied_level": note.applied_level,
            "audio_url": f"/api/v1/voice-notes/{note.id}/audio", "size_bytes": note.size_bytes}


def voice_notes_for(db: Session, incident_ids: list) -> dict:
    """Voice notes keyed by incident id, without loading the audio."""
    if not incident_ids: return {}
    rows = db.scalars(select(VoiceNote).where(VoiceNote.incident_id.in_(incident_ids))).all()
    return {n.incident_id: voice_summary(n) for n in rows}


def _clean(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t").strip()


def _handle(db: Session, request: Request, user, patient_id: uuid.UUID, audio: bytes, mime: str, language_hint: str | None) -> dict:
    from app.main import PatientMessageIn, create_message, patient_access
    from app.models import Role
    patient, _ = patient_access(db, user, patient_id)
    key = request.headers.get("Idempotency-Key")
    if key:  # a retried upload returns the first result instead of transcribing and routing twice
        prior = db.scalar(select(PatientMessage).where(PatientMessage.sender_user_id == user.id, PatientMessage.idempotency_key == key, PatientMessage.patient_id == patient.id))
        if prior and prior.incident_id:
            note = db.scalar(select(VoiceNote).where(VoiceNote.incident_id == prior.incident_id))
            from app.main import incident_payload
            return {**incident_payload(db.get(Incident, prior.incident_id)), "voice_note": voice_summary(note) if note else None}

    heard = ai.transcribe_audio(audio, mime, language_hint)
    text = _clean(heard.text)[:1000] if heard else ""
    advisor = ai.urgency_advisor() if text else None
    body = PatientMessageIn(body=text or UNHEARD, channel="VOICE", language_hint=(heard.language if heard and heard.language else language_hint), on_behalf=user.role != Role.PATIENT)
    incident = create_message(patient_id, body, request, user, db, advisor=advisor)
    note = VoiceNote(patient_id=patient.id, sender_user_id=user.id, incident_id=incident["id"], mime_type=mime[:60], size_bytes=len(audio), audio=audio,
                     status="TRANSCRIBED" if text else "UNTRANSCRIBED", transcript=text, language=heard.language if heard else None,
                     confidence=heard.confidence if heard else None, stt_provider=heard.provider if heard else None, stt_model=heard.model if heard else None)
    if advisor is not None and advisor.level is not None:
        note.suggested_level, note.suggested_reason, note.advisor_provider = advisor.level, advisor.reason, advisor.provider
        note.applied_level = getattr(advisor, "applied", None)
    db.add(note); db.commit()
    return {**incident, "voice_note": voice_summary(note)}


@router.post("/patients/{patient_id}/voice-notes", status_code=201)
async def upload_voice_note(patient_id: uuid.UUID, request: Request, language: str | None = None, user=Depends(_current_user), db: Session = Depends(get_db)):
    """Body is the raw audio (Content-Type audio/webm, audio/ogg, audio/mp4 ...). Works with no AI keys: it is then stored and routed for a person to listen."""
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime not in ALLOWED: raise HTTPException(415, "Send the recording as audio (webm, ogg, mp4, mp3 or wav)")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.voice_max_bytes: raise HTTPException(413, "That recording is too long. Keep voice notes under a minute.")
    audio = await request.body()
    if len(audio) > settings.voice_max_bytes: raise HTTPException(413, "That recording is too long. Keep voice notes under a minute.")
    if len(audio) < MIN_BYTES: raise HTTPException(422, "That recording is too short to send")
    hint = language.strip().lower()[:8] if language and language.strip().isalpha() else None
    return await run_in_threadpool(_handle, db, request, user, patient_id, audio, request.headers.get("content-type", mime), hint)


@router.get("/voice-notes/{note_id}/audio")
def voice_note_audio(note_id: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    from app.main import may_read_incident, patient_access
    note = db.get(VoiceNote, note_id)
    if not note: raise HTTPException(404, "Voice note not found")
    _, member = patient_access(db, user, note.patient_id)
    incident = db.get(Incident, note.incident_id) if note.incident_id else None
    if incident is not None and not may_read_incident(db, incident, user, member): raise HTTPException(403, "Voice note access denied")
    if incident is None and note.sender_user_id != user.id: raise HTTPException(403, "Voice note access denied")
    return Response(content=note.audio, media_type=note.mime_type.split(";")[0], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
