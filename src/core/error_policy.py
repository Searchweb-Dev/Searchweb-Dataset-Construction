"""LLM API 에러 코드별 처리 정책.

에러 유형을 분류하고, 각 유형에 따라 어떤 예외를 발생시킬지 결정한다.
새로운 에러 유형이 추가될 때 이 파일만 수정하면 된다.

분류 우선순위:
  1. Gemini SDK ClientError/ServerError 타입 + .code + .status 속성 활용 (정확)
  2. 문자열 패턴 매칭 (폴백)

Gemini gRPC status → HTTP 코드 매핑:
  INVALID_ARGUMENT      → 400  사이트 접근 불가 (URL_CONTEXT 수집 실패)
  FAILED_PRECONDITION   → 400  사전 조건 미충족 (기능 미활성 등)
  NOT_FOUND             → 404  리소스 없음
  PERMISSION_DENIED     → 403  권한 없음
  UNAUTHENTICATED       → 401  인증 실패
  RESOURCE_EXHAUSTED    → 429  할당량 초과
  DEADLINE_EXCEEDED     → 504  타임아웃
  UNAVAILABLE           → 503  서버 일시 불가
  INTERNAL              → 500  서버 내부 오류
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum



class ApiErrorKind(StrEnum):
    """API 에러 종류."""

    # 4xx — 클라이언트/요청 문제
    UNREACHABLE = "unreachable"            # 400 INVALID_ARGUMENT — URL_CONTEXT 수집 실패
    PRECONDITION_FAILED = "precondition"   # 400 FAILED_PRECONDITION — 기능 미활성 등
    NOT_FOUND = "not_found"                # 404 NOT_FOUND — 리소스 없음
    AUTH_ERROR = "auth_error"              # 401 UNAUTHENTICATED — 인증 실패
    PERMISSION_DENIED = "permission"       # 403 PERMISSION_DENIED — 권한 없음
    RATE_LIMITED = "rate_limited"          # 429 RESOURCE_EXHAUSTED — 할당량 초과

    # 5xx — 서버/인프라 문제
    TIMEOUT = "timeout"                    # 504 DEADLINE_EXCEEDED — 타임아웃
    SERVER_UNAVAILABLE = "unavailable"     # 503 UNAVAILABLE — 서버 일시 불가
    SERVER_INTERNAL = "internal"           # 500 INTERNAL — 서버 내부 오류

    UNKNOWN = "unknown"                    # 분류 불가


@dataclass(frozen=True)
class ErrorPolicy:
    """에러 종류별 처리 정책."""

    kind: ApiErrorKind
    retryable: bool         # 재시도 의미 있음 여부
    mark_unreachable: bool  # DB에 unreachable_since 기록 여부
    log_level: str          # "warning" | "error"
    description: str        # 로그/메시지용 한글 설명
    site_status: str | None = None  # ai_site.status 설정값. None이면 ai_site 건드리지 않음


POLICIES: dict[ApiErrorKind, ErrorPolicy] = {
    ApiErrorKind.UNREACHABLE: ErrorPolicy(
        kind=ApiErrorKind.UNREACHABLE,
        retryable=False,
        mark_unreachable=True,
        log_level="warning",
        description="사이트 접근 불가 (400/INVALID_ARGUMENT)",
        site_status="unreachable",
    ),
    ApiErrorKind.PRECONDITION_FAILED: ErrorPolicy(
        kind=ApiErrorKind.PRECONDITION_FAILED,
        retryable=False,
        mark_unreachable=False,
        log_level="error",
        description="사전 조건 미충족 (400/FAILED_PRECONDITION)",
        site_status="blocked",
    ),
    ApiErrorKind.NOT_FOUND: ErrorPolicy(
        kind=ApiErrorKind.NOT_FOUND,
        retryable=False,
        mark_unreachable=True,
        log_level="warning",
        description="리소스 없음 (404/NOT_FOUND)",
        site_status="unreachable",
    ),
    ApiErrorKind.AUTH_ERROR: ErrorPolicy(
        kind=ApiErrorKind.AUTH_ERROR,
        retryable=False,
        mark_unreachable=False,
        log_level="error",
        description="API 인증 실패 (401/UNAUTHENTICATED)",
        site_status="blocked",
    ),
    ApiErrorKind.PERMISSION_DENIED: ErrorPolicy(
        kind=ApiErrorKind.PERMISSION_DENIED,
        retryable=False,
        mark_unreachable=False,
        log_level="error",
        description="API 권한 없음 (403/PERMISSION_DENIED)",
        site_status="blocked",
    ),
    ApiErrorKind.RATE_LIMITED: ErrorPolicy(
        kind=ApiErrorKind.RATE_LIMITED,
        retryable=True,
        mark_unreachable=False,
        log_level="warning",
        description="API 할당량 초과 (429/RESOURCE_EXHAUSTED)",
        site_status=None,
    ),
    ApiErrorKind.TIMEOUT: ErrorPolicy(
        kind=ApiErrorKind.TIMEOUT,
        retryable=True,
        mark_unreachable=False,
        log_level="warning",
        description="요청 타임아웃 (504/DEADLINE_EXCEEDED)",
        site_status=None,
    ),
    ApiErrorKind.SERVER_UNAVAILABLE: ErrorPolicy(
        kind=ApiErrorKind.SERVER_UNAVAILABLE,
        retryable=True,
        mark_unreachable=False,
        log_level="warning",
        description="API 서버 일시 불가 (503/UNAVAILABLE)",
        site_status=None,
    ),
    ApiErrorKind.SERVER_INTERNAL: ErrorPolicy(
        kind=ApiErrorKind.SERVER_INTERNAL,
        retryable=True,
        mark_unreachable=False,
        log_level="error",
        description="API 서버 내부 오류 (500/INTERNAL)",
        site_status=None,
    ),
    ApiErrorKind.UNKNOWN: ErrorPolicy(
        kind=ApiErrorKind.UNKNOWN,
        retryable=True,
        mark_unreachable=False,
        log_level="error",
        description="알 수 없는 오류",
        site_status="failure",
    ),
}


def classify_api_error(exc: BaseException) -> ApiErrorKind:
    """예외로부터 API 에러 종류를 분류한다.

    Gemini SDK ClientError/ServerError의 .code와 .status를 우선 활용하고,
    그 외 예외는 문자열 패턴 매칭으로 폴백한다.
    """
    try:
        from google.genai.errors import ClientError, ServerError
        if isinstance(exc, ClientError):
            return _classify_client_error(exc)
        if isinstance(exc, ServerError):
            return _classify_server_error(exc)
    except ImportError:
        pass

    return _classify_by_message(str(exc).lower())


def get_policy(exc: BaseException) -> ErrorPolicy:
    """예외로부터 처리 정책을 반환한다."""
    kind = classify_api_error(exc)
    return POLICIES[kind]


def _classify_client_error(exc: object) -> ApiErrorKind:
    """Gemini ClientError(4xx)를 status/code로 세분화한다."""
    code: int = getattr(exc, "code", 0) or 0
    status: str = (getattr(exc, "status", "") or "").upper()

    if status == "INVALID_ARGUMENT" or code == 400:
        msg = str(exc).lower()
        if "failed_precondition" in msg or "precondition" in msg:
            return ApiErrorKind.PRECONDITION_FAILED
        return ApiErrorKind.UNREACHABLE
    if status == "FAILED_PRECONDITION":
        return ApiErrorKind.PRECONDITION_FAILED
    if status == "NOT_FOUND" or code == 404:
        return ApiErrorKind.NOT_FOUND
    if status == "UNAUTHENTICATED" or code == 401:
        return ApiErrorKind.AUTH_ERROR
    if status == "PERMISSION_DENIED" or code == 403:
        return ApiErrorKind.PERMISSION_DENIED
    if status == "RESOURCE_EXHAUSTED" or code == 429:
        return ApiErrorKind.RATE_LIMITED

    if 400 <= code < 500:
        return _classify_by_message(str(exc).lower())
    return ApiErrorKind.UNKNOWN


def _classify_server_error(exc: object) -> ApiErrorKind:
    """Gemini ServerError(5xx)를 status/code로 세분화한다."""
    code: int = getattr(exc, "code", 0) or 0
    status: str = (getattr(exc, "status", "") or "").upper()

    if status == "DEADLINE_EXCEEDED" or code == 504:
        return ApiErrorKind.TIMEOUT
    if status == "UNAVAILABLE" or code == 503:
        return ApiErrorKind.SERVER_UNAVAILABLE
    if status == "INTERNAL" or code == 500:
        return ApiErrorKind.SERVER_INTERNAL

    if 500 <= code < 600:
        return ApiErrorKind.SERVER_INTERNAL
    return ApiErrorKind.UNKNOWN


def _classify_by_message(msg: str) -> ApiErrorKind:
    """문자열 패턴 기반 분류 (SDK 외 예외 폴백용)."""
    if _matches(msg, ("failed_precondition", "precondition")):
        return ApiErrorKind.PRECONDITION_FAILED
    if _matches(msg, ("invalid_argument",)):
        return ApiErrorKind.UNREACHABLE
    if _matches(msg, ("not_found", "404")):
        return ApiErrorKind.NOT_FOUND
    if _matches(msg, ("unauthenticated", "401")):
        return ApiErrorKind.AUTH_ERROR
    if _matches(msg, ("permission_denied", "403")):
        return ApiErrorKind.PERMISSION_DENIED
    if _matches(msg, ("resource_exhausted", "429")):
        return ApiErrorKind.RATE_LIMITED
    if _matches(msg, ("deadline_exceeded", "504", "timed out", "timeout")):
        return ApiErrorKind.TIMEOUT
    if _matches(msg, ("unavailable", "503")):
        return ApiErrorKind.SERVER_UNAVAILABLE
    if _matches(msg, ("internal", "500")):
        return ApiErrorKind.SERVER_INTERNAL
    if "400" in msg:
        return ApiErrorKind.UNREACHABLE

    return ApiErrorKind.UNKNOWN


def _matches(msg: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in msg for kw in keywords)
