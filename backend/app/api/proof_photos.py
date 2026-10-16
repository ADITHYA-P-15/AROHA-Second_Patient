"""Caretaker accountability: a photo is required before a medicine dose can be recorded as given.

Backend is the source of truth: `require_proof_photo` (called from `activities/{aid}/complete`) is what actually blocks
completion, not the UI. The photo's timestamp and location are reported by the client (it already burned them into the
image, visibly, before upload) and stored as structured fields too, so the care team can see them without opening the
photo. Uploaded once; never replaced after the activity is completed, so the evidence cannot be swapped in after the fact.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.db import get_db
from app.core.features import feature_required
from app.core.permissions import require_patient_access
from app.models import ActivityProofPhoto, CareActivity, CareAssignment, CaregiverPatientLink, Caregiver, CareTeamMember, TeamRole

router = APIRouter(prefix="/api/v1", tags=["proof photos"], dependencies=[Depends(feature_required("proof_photos"))])
ALLOWED = ("image/jpeg", "image/png", "image/webp")
MIN_BYTES, MAX_BYTES = 500, 8 * 1024 * 1024


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _may_record_done(db, user, aid, patient_id) -> bool:
    """Same rule as recording an activity as done: the primary contact, or the caretaker it is confirmed-assigned to."""
    own = db.scalar(select(Caregiver).where(Caregiver.user_id == user.id, Caregiver.id.in_(select(CaregiverPatientLink.caregiver_id).where(CaregiverPatientLink.patient_id == patient_id))))
    member = db.scalar(select(CareTeamMember).where(CareTeamMember.patient_id == patient_id, CareTeamMember.user_id == user.id))
    coordinator = (member and member.team_role == TeamRole.PRIMARY_CONTACT)
    return bool(coordinator) or bool(own and db.scalar(select(CareAssignment.id).where(CareAssignment.activity_id == aid, CareAssignment.caregiver_id == own.id, CareAssignment.status == "CONFIRMED")))


def _activity_or_404(db, aid) -> CareActivity:
    a = db.get(CareActivity, aid)
    if not a: raise HTTPException(404, "Activity not found")
    return a


def require_proof_photo(db: Session, activity: CareActivity) -> None:
    """Called from activities/{aid}/complete: block completion of a medicine dose with no uploaded proof photo."""
    from app.core.config import settings
    if not settings.feature("proof_photos"): return  # feature dark: do not block completion on a photo no one can upload
    if activity.source != "PRESCRIPTION": return  # only medicine doses need a proof photo
    has_photo = db.scalar(select(ActivityProofPhoto.id).where(ActivityProofPhoto.activity_id == activity.id)) is not None
    if not has_photo: raise HTTPException(422, "Take a photo of giving this dose before you can record it as done")


def _meta(photo: ActivityProofPhoto) -> dict:
    return {"activity_id": photo.activity_id, "uploaded_by": photo.uploaded_by, "mime_type": photo.mime_type, "size_bytes": photo.size_bytes,
            "captured_at": photo.captured_at, "latitude": photo.latitude, "longitude": photo.longitude, "location_accuracy_m": photo.location_accuracy_m,
            "location_status": photo.location_status, "created_at": photo.created_at, "photo_url": f"/api/v1/activities/{photo.activity_id}/proof-photo"}


@router.put("/activities/{aid}/proof-photo", status_code=201)
async def upload_proof_photo(aid: uuid.UUID, request: Request, latitude: float | None = None, longitude: float | None = None,
                             accuracy_m: float | None = None, location_status: str = "UNAVAILABLE", captured_at: datetime | None = None,
                             user=Depends(_current_user), db: Session = Depends(get_db)):
    """The caretaker (or primary contact) uploads the dose photo. Body is the raw image; location comes from the device."""
    a = _activity_or_404(db, aid)
    require_patient_access(db, user, a.patient_id, "patient:read")
    if not _may_record_done(db, user, aid, a.patient_id): raise HTTPException(403, "Only the primary contact or the assigned caretaker can add this photo")
    if a.source != "PRESCRIPTION": raise HTTPException(409, "Proof photos are only used for medicine doses")
    if a.lifecycle_status == "COMPLETED": raise HTTPException(409, "This dose is already recorded as done; its proof photo cannot be changed")
    mime = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if mime not in ALLOWED: raise HTTPException(415, "Send the photo as an image (jpeg, png or webp)")
    image = await request.body()
    if len(image) > MAX_BYTES: raise HTTPException(413, "That photo is too large")
    if len(image) < MIN_BYTES: raise HTTPException(422, "That does not look like a photo")
    if location_status not in ("AVAILABLE", "DENIED", "UNAVAILABLE"): raise HTTPException(422, "Unknown location_status")
    when = captured_at or now()
    if when.tzinfo is None:
        from datetime import UTC
        when = when.replace(tzinfo=UTC)
    existing = db.scalar(select(ActivityProofPhoto).where(ActivityProofPhoto.activity_id == aid))
    if existing:
        existing.image, existing.mime_type, existing.size_bytes = image, mime, len(image)
        existing.captured_at, existing.latitude, existing.longitude = when, latitude, longitude
        existing.location_accuracy_m, existing.location_status, existing.uploaded_by = accuracy_m, location_status, user.id
        photo = existing
    else:
        photo = ActivityProofPhoto(activity_id=aid, uploaded_by=user.id, image=image, mime_type=mime, size_bytes=len(image),
                                   captured_at=when, latitude=latitude, longitude=longitude, location_accuracy_m=accuracy_m, location_status=location_status)
        db.add(photo)
    db.commit(); db.refresh(photo)
    return _meta(photo)


@router.get("/activities/{aid}/proof-photo")
def get_proof_photo(aid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    a = _activity_or_404(db, aid)
    require_patient_access(db, user, a.patient_id, "patient:read")
    photo = db.scalar(select(ActivityProofPhoto).where(ActivityProofPhoto.activity_id == aid))
    if not photo: raise HTTPException(404, "No proof photo for this activity")
    return Response(content=photo.image, media_type=photo.mime_type, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/activities/{aid}/proof-photo/meta")
def get_proof_photo_meta(aid: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    a = _activity_or_404(db, aid)
    require_patient_access(db, user, a.patient_id, "patient:read")
    photo = db.scalar(select(ActivityProofPhoto).where(ActivityProofPhoto.activity_id == aid))
    if not photo: raise HTTPException(404, "No proof photo for this activity")
    return _meta(photo)
