"""Feature gates for staged rollout (see settings.features)."""
from fastapi import HTTPException

from app.core.config import settings


def feature_required(name: str):
    def check() -> None:
        if not settings.feature(name): raise HTTPException(404, "Not found")
    return check
