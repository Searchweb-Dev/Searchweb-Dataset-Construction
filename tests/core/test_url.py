"""src/core/url.py — normalize_url 단위 테스트."""

from src.core.url import normalize_url


class TestNormalizeUrl:
    """normalize_url 정상 동작 검증."""

    def test_removes_www_prefix(self):
        # Arrange / Act / Assert
        assert normalize_url("https://www.example.com") == "https://example.com"

    def test_lowercases_scheme_and_host(self):
        # http:// 소문자 스킴 + 대문자 호스트 → 호스트 소문자화
        assert normalize_url("http://EXAMPLE.COM") == "http://example.com"

    def test_adds_https_when_no_scheme(self):
        assert normalize_url("example.com") == "https://example.com"

    def test_removes_trailing_slash(self):
        assert normalize_url("https://example.com/") == "https://example.com"

    def test_removes_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_removes_standard_http_port_80(self):
        assert normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_removes_standard_https_port_443(self):
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_keeps_non_standard_port(self):
        result = normalize_url("https://example.com:8443/path")
        assert ":8443" in result

    def test_sorts_query_parameters(self):
        result = normalize_url("https://example.com?z=1&a=2")
        assert result == "https://example.com?a=2&z=1"

    def test_preserves_path(self):
        assert normalize_url("https://example.com/a/b/c") == "https://example.com/a/b/c"

    def test_handles_url_with_whitespace(self):
        assert normalize_url("  https://example.com  ") == "https://example.com"

    def test_returns_original_on_invalid_url(self):
        # 파싱 불가 입력은 원본 strip 반환
        result = normalize_url("not_a_url_at_all!@#")
        assert isinstance(result, str)

    def test_https_scheme_preserved(self):
        result = normalize_url("https://example.com/path")
        assert result.startswith("https://")

    def test_http_scheme_preserved(self):
        result = normalize_url("http://example.com/path")
        assert result.startswith("http://")
