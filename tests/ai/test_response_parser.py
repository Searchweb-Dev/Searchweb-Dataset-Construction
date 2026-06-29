"""src/ai/response_parser.py — 응답 파서 단위 테스트."""

import json
import pytest
from unittest.mock import MagicMock
from src.ai.response_parser import (
    default_response,
    parse_single,
    parse_batch,
    check_finish_reason,
    compute_quality_fields,
)


class TestDefaultResponse:
    """default_response 구조 검증."""

    def test_has_required_keys(self):
        result = default_response()
        assert "is_ai_tool" in result
        assert "title" in result
        assert "scores" in result
        assert "confidence" in result

    def test_is_ai_tool_false(self):
        assert default_response()["is_ai_tool"] is False

    def test_review_required_true(self):
        assert default_response()["review_required"] is True

    def test_hard_pass_false(self):
        assert default_response()["hard_pass"] is False


class TestParseSingle:
    """parse_single 단건 응답 파싱 검증."""

    def _make_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.text = text
        resp.candidates = [MagicMock()]
        return resp

    def test_parses_valid_json(self):
        payload = {"is_ai_tool": True, "title": "TestAI", "confidence": 0.9}
        resp = self._make_response(json.dumps(payload))
        result = parse_single(resp)
        assert result["is_ai_tool"] is True
        assert result["title"] == "TestAI"

    def test_returns_default_on_invalid_json(self):
        resp = self._make_response("not json {{")
        result = parse_single(resp)
        assert result["is_ai_tool"] is False
        assert result["review_required"] is True

    def test_returns_default_when_text_empty(self):
        resp = self._make_response("")
        result = parse_single(resp)
        assert result == default_response()

    def test_returns_blocked_when_no_candidates(self):
        resp = MagicMock()
        resp.candidates = []  # candidate 없음 = 크롤링 차단
        result = parse_single(resp)
        assert result["anti_bot_blocked"] is True
        assert result["is_ai_tool"] is False


class TestParseBatch:
    """parse_batch 배치 응답 파싱 검증."""

    def _make_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.text = text
        return resp

    def test_parses_results_wrapper(self):
        payload = {"results": [{"is_ai_tool": True, "title": "A"}, {"is_ai_tool": False, "title": "B"}]}
        resp = self._make_response(json.dumps(payload))
        results = parse_batch(resp, ["https://a.com", "https://b.com"])
        assert len(results) == 2
        assert results[0]["is_ai_tool"] is True

    def test_parses_plain_array(self):
        payload = [{"is_ai_tool": True, "title": "A"}]
        resp = self._make_response(json.dumps(payload))
        results = parse_batch(resp, ["https://a.com"])
        assert results[0]["is_ai_tool"] is True

    def test_pads_missing_results_with_default(self):
        payload = {"results": [{"is_ai_tool": True, "title": "A"}]}
        resp = self._make_response(json.dumps(payload))
        results = parse_batch(resp, ["https://a.com", "https://b.com", "https://c.com"])
        assert len(results) == 3
        assert results[1]["is_ai_tool"] is False  # 기본값
        assert results[2]["is_ai_tool"] is False

    def test_replaces_invalid_item_with_default(self):
        payload = {"results": ["not_a_dict"]}
        resp = self._make_response(json.dumps(payload))
        results = parse_batch(resp, ["https://a.com"])
        assert results[0]["is_ai_tool"] is False

    def test_sets_analyzer_gemini(self):
        payload = {"results": [{"is_ai_tool": True, "title": "A"}]}
        resp = self._make_response(json.dumps(payload))
        results = parse_batch(resp, ["https://a.com"])
        assert results[0]["analyzer"] == "gemini"

    def test_returns_empty_for_empty_urls(self):
        resp = self._make_response("{}")
        results = parse_batch(resp, [])
        assert results == []

    def test_returns_default_on_parse_error(self):
        resp = self._make_response("{{invalid")
        results = parse_batch(resp, ["https://a.com"])
        assert len(results) == 1
        assert results[0]["is_ai_tool"] is False


class TestCheckFinishReason:
    """check_finish_reason 로깅 검증 (예외 없이 실행되어야 함)."""

    def _make_response(self, reason_name: str | None = "STOP") -> MagicMock:
        resp = MagicMock()
        if reason_name is None:
            resp.candidates = []
        else:
            candidate = MagicMock()
            finish_reason = MagicMock()
            finish_reason.name = reason_name
            candidate.finish_reason = finish_reason
            resp.candidates = [candidate]
        return resp

    def test_stop_reason_no_exception(self):
        resp = self._make_response("STOP")
        check_finish_reason("https://example.com", resp)  # 예외 없어야 함

    def test_max_tokens_logs_warning(self, caplog):
        import logging
        resp = self._make_response("MAX_TOKENS")
        with caplog.at_level(logging.WARNING):
            check_finish_reason("https://example.com", resp)
        assert any("max_output_tokens" in r.message or "MAX_TOKENS" in r.message for r in caplog.records)

    def test_no_candidates_no_exception(self):
        resp = self._make_response(None)
        check_finish_reason("https://example.com", resp)

    def test_exception_in_response_handled(self):
        resp = MagicMock()
        resp.candidates = None  # NoneType 접근 시 예외
        check_finish_reason("https://example.com", resp)  # 예외가 내부에서 처리됨


class TestComputeQualityFields:
    """compute_quality_fields 파생 필드 계산 검증."""

    def test_total_score_calculation(self):
        result = {
            "scores": {"utility": 8, "trust": 7, "originality": 6},
            "confidence": 0.9,
            "is_ai_tool": True,
        }
        fields = compute_quality_fields(result)
        # (8*0.4 + 7*0.3 + 6*0.3) * 10 = (3.2 + 2.1 + 1.8) * 10 = 71.0
        assert fields["total_score"] == pytest.approx(71.0, abs=0.01)

    def test_hard_pass_when_confident_ai_tool(self):
        result = {"scores": {"utility": 9, "trust": 9, "originality": 9}, "confidence": 0.85, "is_ai_tool": True}
        fields = compute_quality_fields(result)
        assert fields["hard_pass"] is True

    def test_no_hard_pass_when_not_ai_tool(self):
        result = {"scores": {"utility": 9, "trust": 9, "originality": 9}, "confidence": 0.95, "is_ai_tool": False}
        fields = compute_quality_fields(result)
        assert fields["hard_pass"] is False

    def test_no_hard_pass_when_low_confidence(self):
        result = {"scores": {"utility": 9, "trust": 9, "originality": 9}, "confidence": 0.75, "is_ai_tool": True}
        fields = compute_quality_fields(result)
        assert fields["hard_pass"] is False

    def test_review_required_when_low_confidence(self):
        result = {"scores": {}, "confidence": 0.5, "is_ai_tool": True}
        fields = compute_quality_fields(result)
        assert fields["review_required"] is True

    def test_review_required_when_low_score_ai_tool(self):
        result = {"scores": {"utility": 2, "trust": 2, "originality": 2}, "confidence": 0.75, "is_ai_tool": True}
        fields = compute_quality_fields(result)
        assert fields["review_required"] is True

    def test_not_review_required_when_high_confidence_good_score(self):
        result = {"scores": {"utility": 9, "trust": 9, "originality": 9}, "confidence": 0.9, "is_ai_tool": True}
        fields = compute_quality_fields(result)
        assert fields["review_required"] is False

    def test_handles_missing_scores(self):
        result = {"confidence": 0.5, "is_ai_tool": False}
        fields = compute_quality_fields(result)
        assert fields["total_score"] == 0.0

    def test_handles_invalid_scores(self):
        result = {"scores": {"utility": "bad", "trust": None, "originality": 0}, "confidence": 0.5, "is_ai_tool": False}
        fields = compute_quality_fields(result)
        assert fields["total_score"] == 0.0
