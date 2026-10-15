"""Analytics for healthcare professionals over their own patients."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Role
from app.services.insights import professional_insights

router = APIRouter(prefix="/api/v1", tags=["insights"])


def _current_user(request: Request, db: Session = Depends(get_db)):
    from app.main import current_user
    return current_user(request, db)


@router.get("/insights/professional")
def professional(days: int = Query(30, ge=7, le=90), user=Depends(_current_user), db: Session = Depends(get_db)):
    """Adherence, trends and follow-up flags across the patients this professional is on the care team of."""
    if user.role != Role.PROFESSIONAL: raise HTTPException(403, "Only healthcare professionals can view patient analytics")
    return professional_insights(db, user, days)
