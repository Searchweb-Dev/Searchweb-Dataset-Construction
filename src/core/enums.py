"""도메인 열거형."""

from enum import StrEnum


class JobStatus(StrEnum):
    """분석 작업 상태."""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
