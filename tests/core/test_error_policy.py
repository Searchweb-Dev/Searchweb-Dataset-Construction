"""src/core/error_policy.py — 에러 분류 및 정책 단위 테스트."""

import pytest
from unittest.mock import MagicMock
from src.core.error_policy import (
    ApiErrorKind,
    ErrorPolicy,
    POLICIES,
    classify_api_error,
    get_policy,
    _classify_client_error,
    _classify_server_error,
    _classify_by_message,
    _matches,
)


class TestApiErrorKindValues:
    """ApiErrorKind 열거형 값 검증."""

    def test_all_kinds_present(self):
        kinds = {k.value for k in ApiErrorKind}
        assert "rate_limited" in kinds
        assert "timeout" in kinds
        assert "unknown" in kinds

    def test_kind_is_str(self):
        assert isinstance(ApiErrorKind.RATE_LIMITED, str)


class TestPolicies:
    """POLICIES 매핑 일관성 검증."""

    def test_all_kinds_have_policy(self):
        for kind in ApiErrorKind:
            assert kind in POLICIES, f"{kind} POLICIES에 없음"

    def test_rate_limited_is_retryable(self):
        assert POLICIES[ApiErrorKind.RATE_LIMITED].retryable is True

    def test_auth_error_not_retryable(self):
        assert POLICIES[ApiErrorKind.AUTH_ERROR].retryable is False

    def test_unreachable_marks_unreachable(self):
        assert POLICIES[ApiErrorKind.UNREACHABLE].mark_unreachable is True

    def test_rate_limited_no_unreachable(self):
        assert POLICIES[ApiErrorKind.RATE_LIMITED].mark_unreachable is False

    def test_policy_is_frozen(self):
        policy = POLICIES[ApiErrorKind.UNKNOWN]
        with pytest.raises(Exception):
            policy.retryable = False  # type: ignore[misc]


class TestClassifyByMessage:
    """_classify_by_message 문자열 패턴 매칭 검증."""

    @pytest.mark.parametrize("msg,expected", [
        ("resource_exhausted quota exceeded", ApiErrorKind.RATE_LIMITED),
        ("429 too many requests", ApiErrorKind.RATE_LIMITED),
        ("deadline_exceeded", ApiErrorKind.TIMEOUT),
        ("timed out connecting", ApiErrorKind.TIMEOUT),
        ("unavailable service", ApiErrorKind.SERVER_UNAVAILABLE),
        ("503 backend error", ApiErrorKind.SERVER_UNAVAILABLE),
        ("internal server error", ApiErrorKind.SERVER_INTERNAL),
        ("500 oops", ApiErrorKind.SERVER_INTERNAL),
        ("unauthenticated request", ApiErrorKind.AUTH_ERROR),
        ("permission_denied for resource", ApiErrorKind.PERMISSION_DENIED),
        ("not_found resource", ApiErrorKind.NOT_FOUND),
        ("invalid_argument supplied", ApiErrorKind.UNREACHABLE),
        ("400 bad request", ApiErrorKind.UNREACHABLE),
        ("something totally unknown xyz", ApiErrorKind.UNKNOWN),
    ])
    def test_pattern_matching(self, msg, expected):
        assert _classify_by_message(msg) == expected

    def test_precondition_takes_precedence_over_invalid_argument(self):
        result = _classify_by_message("failed_precondition invalid_argument")
        assert result == ApiErrorKind.PRECONDITION_FAILED


class TestClassifyClientError:
    """_classify_client_error Gemini ClientError 분류 검증."""

    def _make_exc(self, code: int = 0, status: str = "", message: str = "") -> object:
        exc = MagicMock()
        exc.code = code
        exc.status = status
        exc.__str__ = lambda self: message
        return exc

    def test_429_resource_exhausted(self):
        exc = self._make_exc(code=429, status="RESOURCE_EXHAUSTED")
        assert _classify_client_error(exc) == ApiErrorKind.RATE_LIMITED

    def test_401_unauthenticated(self):
        exc = self._make_exc(code=401, status="UNAUTHENTICATED")
        assert _classify_client_error(exc) == ApiErrorKind.AUTH_ERROR

    def test_403_permission_denied(self):
        exc = self._make_exc(code=403, status="PERMISSION_DENIED")
        assert _classify_client_error(exc) == ApiErrorKind.PERMISSION_DENIED

    def test_404_not_found(self):
        exc = self._make_exc(code=404, status="NOT_FOUND")
        assert _classify_client_error(exc) == ApiErrorKind.NOT_FOUND

    def test_400_invalid_argument(self):
        exc = self._make_exc(code=400, status="INVALID_ARGUMENT", message="invalid_argument")
        assert _classify_client_error(exc) == ApiErrorKind.UNREACHABLE

    def test_400_precondition(self):
        exc = self._make_exc(code=400, status="INVALID_ARGUMENT", message="failed_precondition")
        assert _classify_client_error(exc) == ApiErrorKind.PRECONDITION_FAILED

    def test_failed_precondition_status(self):
        exc = self._make_exc(code=0, status="FAILED_PRECONDITION")
        assert _classify_client_error(exc) == ApiErrorKind.PRECONDITION_FAILED

    def test_unknown_4xx(self):
        exc = self._make_exc(code=499, status="SOME_NEW_STATUS")
        result = _classify_client_error(exc)
        assert isinstance(result, ApiErrorKind)


class TestClassifyServerError:
    """_classify_server_error Gemini ServerError 분류 검증."""

    def _make_exc(self, code: int = 0, status: str = "") -> object:
        exc = MagicMock()
        exc.code = code
        exc.status = status
        return exc

    def test_504_deadline_exceeded(self):
        exc = self._make_exc(code=504, status="DEADLINE_EXCEEDED")
        assert _classify_server_error(exc) == ApiErrorKind.TIMEOUT

    def test_503_unavailable(self):
        exc = self._make_exc(code=503, status="UNAVAILABLE")
        assert _classify_server_error(exc) == ApiErrorKind.SERVER_UNAVAILABLE

    def test_500_internal(self):
        exc = self._make_exc(code=500, status="INTERNAL")
        assert _classify_server_error(exc) == ApiErrorKind.SERVER_INTERNAL

    def test_generic_5xx(self):
        exc = self._make_exc(code=502)
        assert _classify_server_error(exc) == ApiErrorKind.SERVER_INTERNAL

    def test_unknown_no_code(self):
        exc = self._make_exc(code=0)
        assert _classify_server_error(exc) == ApiErrorKind.UNKNOWN


class TestClassifyApiError:
    """classify_api_error 전체 경로 검증."""

    def test_generic_exception_falls_back_to_message(self):
        exc = RuntimeError("resource_exhausted quota exceeded")
        assert classify_api_error(exc) == ApiErrorKind.RATE_LIMITED

    def test_unknown_exception(self):
        exc = RuntimeError("something completely random")
        assert classify_api_error(exc) == ApiErrorKind.UNKNOWN


class TestGetPolicy:
    """get_policy 반환 정책 검증."""

    def test_returns_error_policy(self):
        exc = RuntimeError("resource_exhausted")
        policy = get_policy(exc)
        assert isinstance(policy, ErrorPolicy)
        assert policy.retryable is True

    def test_unknown_exc_returns_unknown_policy(self):
        exc = RuntimeError("xxxxxx")
        policy = get_policy(exc)
        assert policy.kind == ApiErrorKind.UNKNOWN


class TestMatches:
    """_matches 헬퍼 검증."""

    def test_keyword_present(self):
        assert _matches("the message contains timeout", ("timeout",)) is True

    def test_keyword_absent(self):
        assert _matches("hello world", ("timeout",)) is False

    def test_multiple_keywords_any_match(self):
        assert _matches("something unavailable here", ("timeout", "unavailable")) is True
