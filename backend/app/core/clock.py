from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    """Normalize an aware API/local datetime for portable UTC persistence."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value.astimezone(UTC)
