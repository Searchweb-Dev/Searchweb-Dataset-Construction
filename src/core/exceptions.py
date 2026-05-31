"""도메인 공통 예외 클래스."""


class AnalysisError(RuntimeError):
    """AI 분석 실패 시 발생하는 예외."""


class SiteUnreachableError(AnalysisError):
    """대상 사이트에 접근할 수 없을 때 발생하는 예외 (HTTP 400 등)."""
