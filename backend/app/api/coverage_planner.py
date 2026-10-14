"""Predictive Coverage Planner: 24 h / 3 day / 7 day coverage forecast and its measures."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.db import get_db
from app.services import coverage_planner as svc

router = APIRouter(prefix="/api/v1", tags=["coverage planner"])


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


def _scope(db, user, patient_id):
    from app.api.workload import _scope as workload_scope
    try:
        return workload_scope(db, user, patient_id)
    except HTTPException as exc:
        if exc.status_code != 403: raise
        raise HTTPException(403, "The coverage forecast is available to primary contacts and family contacts") from None


@router.get("/patients/{patient_id}/coverage-forecast")
def coverage_forecast(patient_id: uuid.UUID, user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, role_view = _scope(db, user, patient_id)
    at = now()
    result = svc.plan(db, patient.id, at)  # read-only: the 60-second scheduler owns the findings log
    can_act = role_view in {"COORDINATOR", "ADMIN"}
    if not can_act:
        for finding in result["findings"]:
            if finding["holder"]: finding["holder"]["assignment_id"] = None
    return {"patient": {"id": patient.id, "name": patient.name, "is_synthetic": patient.is_synthetic}, "as_of": at,
            "timezone": settings.app_timezone, "role_view": role_view, "permissions": {"can_act": can_act}, **result}


@router.get("/patients/{patient_id}/coverage-forecast/metrics")
def coverage_forecast_metrics(patient_id: uuid.UUID, days: int = Query(30, ge=1, le=365), user=Depends(_current_user), db: Session = Depends(get_db)):
    patient, _ = _scope(db, user, patient_id)
    return svc.metrics(db, patient.id, days)
