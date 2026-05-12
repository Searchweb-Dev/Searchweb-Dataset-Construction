"""공통 유틸리티 함수."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """naive UTC datetime 반환 (DB DateTime(timezone=False) 대응)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
