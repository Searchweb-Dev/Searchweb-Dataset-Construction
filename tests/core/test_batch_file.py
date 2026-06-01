"""src/core/batch_file.py — URL 추출 단위 테스트."""

import json
import os
import tempfile
import pytest
from src.core.batch_file import (
    extract_urls_from_bytes,
    extract_urls_from_path,
    _looks_like_json,
    _parse_json,
    _parse_text,
)


class TestLooksLikeJson:
    """_looks_like_json 내용 기반 JSON 판별 검증."""

    def test_array_start(self):
        assert _looks_like_json(b'["https://example.com"]') is True

    def test_object_start(self):
        assert _looks_like_json(b'{"results": []}') is True

    def test_plain_text(self):
        assert _looks_like_json(b"https://example.com\nhttps://foo.com") is False

    def test_whitespace_before_bracket(self):
        assert _looks_like_json(b'  ["url"]') is True


class TestParseJson:
    """_parse_json 다양한 형식 파싱 검증."""

    def test_string_array(self):
        content = json.dumps(["https://a.com", "https://b.com"]).encode()
        result = _parse_json(content)
        assert result == ["https://a.com", "https://b.com"]

    def test_object_array_with_link_key(self):
        content = json.dumps([{"link": "https://a.com"}, {"link": "https://b.com"}]).encode()
        result = _parse_json(content)
        assert "https://a.com" in result

    def test_object_array_with_url_key(self):
        content = json.dumps([{"url": "https://a.com"}]).encode()
        result = _parse_json(content)
        assert "https://a.com" in result

    def test_skips_already_processed_items(self):
        # is_ai_tool이 있고 error 없으면 스킵
        content = json.dumps([
            {"link": "https://a.com", "is_ai_tool": True},
            {"link": "https://b.com"},
        ]).encode()
        result = _parse_json(content)
        assert "https://a.com" not in result
        assert "https://b.com" in result

    def test_includes_failed_items(self):
        # is_ai_tool 있어도 error 있으면 포함
        content = json.dumps([
            {"link": "https://a.com", "is_ai_tool": False, "error": "timeout"},
        ]).encode()
        result = _parse_json(content)
        assert "https://a.com" in result

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="JSON 파싱 실패"):
            _parse_json(b"not valid json {{{")

    def test_raises_on_non_array_json(self):
        with pytest.raises(ValueError, match="배열 형식"):
            _parse_json(b'{"key": "value"}')

    def test_strips_whitespace_from_urls(self):
        content = json.dumps(["  https://a.com  "]).encode()
        result = _parse_json(content)
        assert result == ["https://a.com"]


class TestParseText:
    """_parse_text 텍스트 파싱 검증."""

    def test_one_url_per_line(self):
        content = b"https://a.com\nhttps://b.com\nhttps://c.com"
        result = _parse_text(content)
        assert result == ["https://a.com", "https://b.com", "https://c.com"]

    def test_skips_empty_lines(self):
        content = b"https://a.com\n\nhttps://b.com\n"
        result = _parse_text(content)
        assert len(result) == 2

    def test_strips_whitespace(self):
        content = b"  https://a.com  \n  https://b.com  "
        result = _parse_text(content)
        assert result == ["https://a.com", "https://b.com"]

    def test_handles_utf8_decode_error(self):
        content = b"\xff\xfe" + b"https://a.com"
        result = _parse_text(content)
        assert any("https://a.com" in u or len(u) > 0 for u in result)


class TestExtractUrlsFromBytes:
    """extract_urls_from_bytes 통합 검증."""

    def test_json_file_by_extension(self):
        content = json.dumps(["https://a.com"]).encode()
        result = extract_urls_from_bytes(content, filename="urls.json")
        assert result == ["https://a.com"]

    def test_text_file_by_extension(self):
        content = b"https://a.com\nhttps://b.com"
        result = extract_urls_from_bytes(content, filename="urls.txt")
        assert result == ["https://a.com", "https://b.com"]

    def test_auto_detect_json(self):
        content = json.dumps(["https://a.com"]).encode()
        result = extract_urls_from_bytes(content)
        assert result == ["https://a.com"]

    def test_auto_detect_text(self):
        content = b"https://a.com\nhttps://b.com"
        result = extract_urls_from_bytes(content)
        assert result == ["https://a.com", "https://b.com"]

    def test_raises_when_no_urls(self):
        with pytest.raises(ValueError, match="유효한 URL"):
            extract_urls_from_bytes(b"", filename="empty.txt")

    def test_truncates_to_max_500(self):
        urls = [f"https://site{i}.com" for i in range(600)]
        content = json.dumps(urls).encode()
        result = extract_urls_from_bytes(content, filename="urls.json")
        assert len(result) == 500


class TestExtractUrlsFromPath:
    """extract_urls_from_path 경로 보안 검증."""

    def test_raises_on_path_traversal(self):
        with pytest.raises(ValueError, match="허용되지 않는 경로"):
            extract_urls_from_path("/etc/passwd")

    def test_raises_on_nonexistent_file(self, tmp_path, monkeypatch):
        # _ALLOWED_BASE를 tmp_path로 패치하여 경로 검증 통과
        import src.core.batch_file as bf
        monkeypatch.setattr(bf, "_ALLOWED_BASE", str(tmp_path))
        with pytest.raises(FileNotFoundError):
            extract_urls_from_path(str(tmp_path / "no_such_file.json"))

    def test_reads_valid_file(self, tmp_path, monkeypatch):
        import src.core.batch_file as bf
        monkeypatch.setattr(bf, "_ALLOWED_BASE", str(tmp_path))
        f = tmp_path / "urls.txt"
        f.write_text("https://a.com\nhttps://b.com")
        result = extract_urls_from_path(str(f))
        assert result == ["https://a.com", "https://b.com"]
