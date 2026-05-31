"""도메인 공통 예외 클래스."""

class AnalysisError(RuntimeError):
    """AI 분석 실패 시 발생하는 예외."""

class SiteUnreachableError(AnalysisError):
    """대상 사이트에 접근할 수 없을 때 발생하는 예외 (HTTP 400 등)."""


# ---------------------------------------------------------------------------
# API 전용 예외 — error_policy.ApiErrorKind와 1:1 대응
# ---------------------------------------------------------------------------

class RateLimitError(AnalysisError):
    """API 할당량 초과 시 발생하는 예외 (429/RESOURCE_EXHAUSTED)."""

class ApiServerError(AnalysisError):
    """LLM API 서버 측 오류 (5xx) 기반 예외."""

class ApiServerUnavailableError(ApiServerError):
    """API 서버 일시 불가 예외 (503/UNAVAILABLE)."""

class ApiServerInternalError(ApiServerError):
    """API 서버 내부 오류 예외 (500/INTERNAL)."""

class ApiAuthError(AnalysisError):
    """API 인증/권한 오류 기반 예외."""

class ApiUnauthenticatedError(ApiAuthError):
    """API 인증 실패 예외 (401/UNAUTHENTICATED)."""

class ApiPermissionDeniedError(ApiAuthError):
    """API 권한 없음 예외 (403/PERMISSION_DENIED)."""

class ApiTimeoutError(AnalysisError):
    """API 요청 타임아웃 예외 (504/DEADLINE_EXCEEDED)."""

class ApiPreconditionError(AnalysisError):
    """API 사전 조건 미충족 예외 (400/FAILED_PRECONDITION)."""

class ApiNotFoundError(AnalysisError):
    """API 리소스 없음 예외 (404/NOT_FOUND). unreachable로 처리한다."""
