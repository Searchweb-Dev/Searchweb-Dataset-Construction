"""src/core/result_writer.py — 결과 파일 저장 단위 테스트."""

import json
import os
import pytest
from unittest.mock import patch
from src.core.result_writer import (
    _favicon_url,
    _output_path,
    _load_source,
    _to_entry,
    _to_failed_entry,
    extract_unprocessed,
    write_batch,
)


class TestFaviconUrl:
    """_favicon_url URL 조합 검증."""

    def test_standard_url(self):
        result = _favicon_url("https://example.com/page")
        assert result == "https://example.com/favicon.ico"

    def test_http_url(self):
        result = _favicon_url("http://example.com")
        assert result == "http://example.com/favicon.ico"

    def test_invalid_url_returns_empty(self):
        result = _favicon_url("not-a-url")
        assert result == ""


class TestOutputPath:
    """_output_path 타임스탬프 경로 생성 검증."""

    def test_appends_timestamp(self):
        result = _output_path("2024-01-15T10:30:00", "/data/ai-tools.json")
        assert "20240115_103000" in result
        assert result.endswith(".json")

    def test_removes_existing_timestamp_suffix(self):
        result = _output_path("2024-01-15T10:30:00", "/data/ai-tools_20230101_120000.json")
        # 기존 타임스탬프가 제거되고 새 타임스탬프가 붙어야 함
        assert "20240115_103000" in result

    def test_output_in_data_dir(self):
        from src.core import result_writer
        result = _output_path("2024-01-15T10:30:00", "/some/path/file.json")
        assert result.startswith(result_writer._DATA_DIR)


class TestLoadSource:
    """_load_source 파일 읽기 검증."""

    def test_returns_empty_list_when_no_file(self, tmp_path):
        result = _load_source(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_loads_valid_json(self, tmp_path):
        data = [{"link": "https://a.com"}, {"link": "https://b.com"}]
        f = tmp_path / "data.json"
        f.write_text(json.dumps(data))
        result = _load_source(str(f))
        assert len(result) == 2

    def test_filters_non_dict_items(self, tmp_path):
        data = [{"link": "https://a.com"}, "string_item", 42]
        f = tmp_path / "data.json"
        f.write_text(json.dumps(data))
        result = _load_source(str(f))
        assert len(result) == 1

    def test_returns_empty_on_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json {{")
        result = _load_source(str(f))
        assert result == []


class TestToEntry:
    """_to_entry 분석 결과 변환 검증."""

    def test_basic_conversion(self):
        analysis = {
            "title": "TestAI",
            "description": "AI 도구",
            "is_ai_tool": True,
            "confidence": 0.95,
            "tags": ["ai", "tool"],
            "scores": {"utility": 8, "trust": 7, "originality": 6},
            "categories": [{"level_1": "AI", "level_2": "Chat", "is_primary": True}],
            "analyzer": "gemini",
        }
        entry = _to_entry("https://example.com", analysis, "2024-01-01T00:00:00")
        assert entry["name"] == "TestAI"
        assert entry["is_ai_tool"] is True
        assert entry["link"] == "https://example.com"
        assert entry["img"] == "https://example.com/favicon.ico"
        assert entry["category"] == "Chat"

    def test_uses_primary_category(self):
        analysis = {
            "categories": [
                {"level_1": "A", "level_2": "Sub-A", "is_primary": False},
                {"level_1": "B", "level_2": "Sub-B", "is_primary": True},
            ],
        }
        entry = _to_entry("https://example.com", analysis, "2024-01-01")
        assert entry["category"] == "Sub-B"

    def test_empty_categories_fallback(self):
        entry = _to_entry("https://example.com", {}, "2024-01-01")
        assert entry["category"] == ""
        assert entry["is_ai_tool"] is False

    def test_checked_at_set(self):
        entry = _to_entry("https://example.com", {}, "2024-06-01T12:00:00")
        assert entry["checked_at"] == "2024-06-01T12:00:00"


class TestToFailedEntry:
    """_to_failed_entry 실패 항목 변환 검증."""

    def test_contains_error_field(self):
        entry = _to_failed_entry("https://example.com", "timeout", "2024-01-01")
        assert entry["error"] == "timeout"
        assert entry["is_ai_tool"] is False
        assert entry["link"] == "https://example.com"

    def test_empty_name_and_desc(self):
        entry = _to_failed_entry("https://example.com", "error msg", "2024-01-01")
        assert entry["name"] == ""
        assert entry["desc"] == ""


class TestExtractUnprocessed:
    """extract_unprocessed 미처리 항목 추출 검증."""

    def test_returns_none_when_no_unprocessed(self, tmp_path, monkeypatch):
        import src.core.result_writer as rw
        monkeypatch.setattr(rw, "_DATA_DIR", str(tmp_path))
        f = tmp_path / "result.json"
        f.write_text(json.dumps([{"link": "https://a.com", "is_ai_tool": True}]))
        result = extract_unprocessed(str(f))
        assert result is None

    def test_extracts_items_without_is_ai_tool(self, tmp_path, monkeypatch):
        import src.core.result_writer as rw
        monkeypatch.setattr(rw, "_DATA_DIR", str(tmp_path))
        data = [
            {"link": "https://a.com", "is_ai_tool": True},
            {"link": "https://b.com"},  # 미처리 항목
        ]
        f = tmp_path / "result.json"
        f.write_text(json.dumps(data))
        out = extract_unprocessed(str(f))
        assert out is not None
        with open(out) as fp:
            saved = json.load(fp)
        assert len(saved) == 1
        assert saved[0]["link"] == "https://b.com"


class TestWriteBatch:
    """write_batch 배치 저장 검증."""

    def test_returns_none_when_empty(self):
        result = write_batch([], failures=[])
        assert result is None

    def test_writes_results_to_file(self, tmp_path, monkeypatch):
        import src.core.result_writer as rw
        monkeypatch.setattr(rw, "_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(rw, "_SOURCE_PATH", str(tmp_path / "ai-tools.json"))
        results = [
            ("https://example.com", {"title": "Ex", "is_ai_tool": True, "confidence": 0.9, "tags": [], "scores": {}, "categories": [], "analyzer": "gemini"}),
        ]
        out = write_batch(results, checked_at="2024-01-01T00:00:00")
        assert out is not None
        assert os.path.isfile(out)
        with open(out) as f:
            data = json.load(f)
        assert any(item["link"] == "https://example.com" for item in data)

    def test_writes_failures(self, tmp_path, monkeypatch):
        import src.core.result_writer as rw
        monkeypatch.setattr(rw, "_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(rw, "_SOURCE_PATH", str(tmp_path / "ai-tools.json"))
        out = write_batch([], failures=[("https://fail.com", "timeout")], checked_at="2024-01-01T00:00:00")
        assert out is not None
        with open(out) as f:
            data = json.load(f)
        assert any(item.get("error") == "timeout" for item in data)

    def test_updates_existing_entry_by_link(self, tmp_path, monkeypatch):
        import src.core.result_writer as rw
        monkeypatch.setattr(rw, "_DATA_DIR", str(tmp_path))
        source = tmp_path / "ai-tools.json"
        existing = [{"link": "https://example.com", "is_ai_tool": False, "name": "Old"}]
        source.write_text(json.dumps(existing))
        monkeypatch.setattr(rw, "_SOURCE_PATH", str(source))
        results = [
            ("https://example.com", {"title": "New", "is_ai_tool": True, "confidence": 0.9, "tags": [], "scores": {}, "categories": [], "analyzer": "gemini"}),
        ]
        out = write_batch(results, checked_at="2024-01-01T00:00:00", source_path=str(source))
        with open(out) as f:
            data = json.load(f)
        matched = [item for item in data if item["link"] == "https://example.com"]
        assert len(matched) == 1
        assert matched[0]["name"] == "New"
