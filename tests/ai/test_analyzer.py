"""GeminiAnalyzer 및 response_parser 단위 테스트."""

import json
from unittest.mock import Mock, patch
import pytest

from src.ai.gemini_analyzer import GeminiAnalyzer
from src.ai.response_parser import parse_single, parse_batch, default_response


@pytest.fixture
def analyzer():
    """GeminiAnalyzer 인스턴스 (API 호출 없이 생성)."""
    with patch("src.ai.gemini_analyzer.genai.Client"), \
         patch("src.ai.gemini_analyzer.get_gemini_model", return_value="gemini-test"):
        return GeminiAnalyzer(api_key="test-key")


def test_analyzer_initialization(analyzer):
    """분析기 초기화 확인."""
    assert analyzer.model is not None
    assert analyzer.client is not None


def test_parse_single_valid_json(analyzer):
    """단건 응답 파싱 — 정상 JSON."""
    mock_response = Mock()
    mock_response.text = json.dumps({
        "is_ai_tool": True,
        "title": "Test AI",
        "description": "테스트 AI 도구",
        "categories": [{"level_1": "text", "level_2": "text-generation", "is_primary": True}],
        "tags": ["chatbot", "nlp"],
        "scores": {"utility": 8, "trust": 9, "originality": 7},
        "confidence": 0.95,
    })

    result = parse_single(mock_response)

    assert result["is_ai_tool"] is True
    assert result["title"] == "Test AI"
    assert result["confidence"] == 0.95


def test_parse_single_invalid_json(analyzer):
    """단건 응답 파싱 — 파싱 실패 시 기본값 반환."""
    mock_response = Mock()
    mock_response.text = "응답에 JSON이 없습니다."

    result = parse_single(mock_response)

    assert result["is_ai_tool"] is False
    assert result["title"] == "Unknown"
    assert result["confidence"] == 0


def test_parse_batch_valid(analyzer):
    """배치 응답 파싱 — 정상 배열."""
    items = [
        {"is_ai_tool": True, "title": "AI1", "description": "d1",
         "categories": [], "tags": [], "scores": {"utility": 5, "trust": 5, "originality": 5}, "confidence": 0.9},
        {"is_ai_tool": False, "title": "Not AI", "description": "d2",
         "categories": [], "tags": [], "scores": {"utility": 3, "trust": 3, "originality": 3}, "confidence": 0.1},
    ]
    mock_response = Mock()
    mock_response.text = json.dumps(items)

    results = parse_batch(mock_response, ["https://a.com", "https://b.com"])

    assert len(results) == 2
    assert results[0]["is_ai_tool"] is True
    assert results[1]["is_ai_tool"] is False
    assert all(r["analyzer"] == "gemini" for r in results)


def test_parse_batch_length_mismatch(analyzer):
    """배치 응답 길이 불일치 — 기본값으로 패딩."""
    mock_response = Mock()
    mock_response.text = json.dumps([
        {"is_ai_tool": True, "title": "Only One", "description": "d",
         "categories": [], "tags": [], "scores": {"utility": 5, "trust": 5, "originality": 5}, "confidence": 0.9},
    ])

    results = parse_batch(mock_response, ["https://a.com", "https://b.com", "https://c.com"])

    assert len(results) == 3
    assert results[0]["title"] == "Only One"
    assert results[1]["title"] == "Unknown"
    assert results[2]["title"] == "Unknown"


def test_parse_batch_invalid_json(analyzer):
    """배치 응답 파싱 실패 — 전체 기본값 반환."""
    mock_response = Mock()
    mock_response.text = "invalid json"

    results = parse_batch(mock_response, ["https://a.com", "https://b.com"])

    assert len(results) == 2
    assert all(r["title"] == "Unknown" for r in results)


def test_default_response(analyzer):
    """기본 응답 구조 확인."""
    result = default_response()

    assert result["is_ai_tool"] is False
    assert result["confidence"] == 0
    assert "scores" in result
