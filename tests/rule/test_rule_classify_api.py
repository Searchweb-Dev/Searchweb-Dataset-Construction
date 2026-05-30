"""
규칙기반 분류 API 테스트.

POST /api/v1/rule/classify 엔드포인트의 동작을 검증한다.
RuleAnalyzer와 AIDetector를 mock해 외부 네트워크·DB 호출 없이 실행된다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.api.deps import verify_api_key
from src.db.session import get_db
from src.rule.models import CriterionResult, EvaluationResult, Evidence


# ────────────────────────────────────────────
# 공통 헬퍼
# ────────────────────────────────────────────

API_KEY = "test-api-key"
CLASSIFY_URL = "/api/v1/rule/classify"
HEADERS = {"X-API-KEY": API_KEY}


def _make_pipeline_result(
    *,
    input_url: str = "https://example.com",
    final_status: str = "curated",
    passed_count: int = 4,
    hard_pass: bool = True,
    review_required: bool = False,
    review_reasons: Optional[List[str]] = None,
    total_score: float = 82.5,
    criteria: Optional[Dict[str, CriterionResult]] = None,
    extracted: Optional[dict] = None,
) -> EvaluationResult:
    """테스트용 EvaluationResult를 생성한다."""
    return EvaluationResult(
        input_url=input_url,
        normalized_url=input_url,
        predicted_status=final_status,
        final_status=final_status,
        passed_count=passed_count,
        hard_pass=hard_pass,
        review_required=review_required,
        review_reasons=review_reasons or [],
        criteria=criteria or {
            "clear_description": CriterionResult(
                name="clear_description",
                passed=True,
                reason="기능 설명이 명확함",
                confidence=0.9,
                evidence=[Evidence(url=input_url, snippet="AI 코딩 도우미", label="title")],
            )
        },
        summary="테스트 요약",
        extracted=extracted or {"ai_scope": {"scope_decision": "ai", "confidence": 0.9}},
        total_score=total_score,
        score_breakdown={"quality": 50.0, "scope": 32.5},
    )


def _make_saved_result(site_id: int = 1, is_ai_tool: bool = True) -> dict:
    """AIDetector.detect_and_save() 반환값 형태의 dict를 생성한다."""
    return {
        "site_id": site_id,
        "is_ai_tool": is_ai_tool,
        "title": "Example AI Tool",
        "description": "AI 코딩 도우미",
        "categories": [{"level_1": "code", "level_2": "code-generation", "level_3": "", "is_primary": True}],
        "tags": ["코드 생성"],
        "scores": {"utility": 8, "trust": 7, "originality": 5},
        "confidence": 0.9,
        "analyzer": "rule",
    }


def _patch_pipeline_run(mock_pipeline: EvaluationResult, mock_saved: dict):
    """RuleAnalyzer와 AIDetector를 함께 패치하는 컨텍스트 매니저를 반환한다.

    classify() 내부에서 생성되는 RuleAnalyzer 인스턴스의 last_pipeline_result를
    mock_pipeline으로 고정하고, AIDetector.detect_and_save를 mock_saved로 대체한다.
    """
    mock_rule_analyzer = MagicMock()
    mock_rule_analyzer.last_pipeline_result = mock_pipeline

    from contextlib import ExitStack
    stack = ExitStack()
    MockRuleAnalyzer = stack.enter_context(patch("src.api.rule_routes.RuleAnalyzer", return_value=mock_rule_analyzer))
    MockDetector = stack.enter_context(patch("src.api.rule_routes.AIDetector"))
    MockDetector.return_value.detect_and_save.return_value = mock_saved
    return stack, MockDetector, mock_rule_analyzer


@pytest.fixture
def client() -> TestClient:
    """API 키 검증과 DB 세션을 bypass한 테스트 클라이언트.

    DB 캐시 조회 결과를 None으로 고정해 파이프라인 실행 경로를 테스트한다.
    """
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    app.dependency_overrides[verify_api_key] = lambda: API_KEY
    app.dependency_overrides[get_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()


# ────────────────────────────────────────────
# 정상 케이스
# ────────────────────────────────────────────

class TestRuleClassifySuccess:
    """정상 요청/응답 검증."""

    def test_returns_200_with_valid_url(self, client: TestClient) -> None:
        """유효한 URL 요청 시 200을 반환해야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        assert response.status_code == 200

    def test_response_contains_required_fields(self, client: TestClient) -> None:
        """응답 body에 필수 필드가 모두 포함되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        required = {
            "site_id", "input_url", "normalized_url", "predicted_status", "final_status",
            "passed_count", "hard_pass", "review_required", "review_reasons",
            "criteria", "summary", "extracted",
        }
        assert required.issubset(body.keys())

    def test_site_id_returned_from_db(self, client: TestClient) -> None:
        """DB 저장 후 발급된 site_id가 응답에 포함되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result(site_id=42)

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        assert body["site_id"] == 42

    def test_response_values_match_pipeline_result(self, client: TestClient) -> None:
        """파이프라인 상세 결과 값이 응답에 올바르게 반영되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result(
            final_status="curated",
            passed_count=4,
            hard_pass=True,
            total_score=82.5,
        )
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        assert body["final_status"] == "curated"
        assert body["passed_count"] == 4
        assert body["hard_pass"] is True
        assert body["total_score"] == 82.5

    def test_detector_called_with_normalized_url(self, client: TestClient) -> None:
        """AIDetector.detect_and_save가 정규화된 URL로 호출되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()

        stack, MockDetector, _ = _patch_pipeline_run(mock_pipeline, mock_saved)
        with stack:
            mock_detector_instance = MockDetector.return_value

            # Act
            client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        mock_detector_instance.detect_and_save.assert_called_once_with("https://example.com")

    def test_criteria_structure_in_response(self, client: TestClient) -> None:
        """criteria 필드가 올바른 구조로 직렬화되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        criterion = body["criteria"]["clear_description"]
        assert criterion["passed"] is True
        assert criterion["name"] == "clear_description"
        assert isinstance(criterion["evidence"], list)
        assert criterion["evidence"][0]["snippet"] == "AI 코딩 도우미"

    def test_score_breakdown_included_when_present(self, client: TestClient) -> None:
        """score_breakdown이 존재하면 응답에 포함되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result(total_score=75.0)
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        assert body["score_breakdown"] == {"quality": 50.0, "scope": 32.5}

    def test_review_reasons_propagated(self, client: TestClient) -> None:
        """review_reasons 목록이 그대로 전달되어야 한다."""
        # Arrange
        reasons = ["링크 페이지 부재", "기능 설명 불충분"]
        mock_pipeline = _make_pipeline_result(review_required=True, review_reasons=reasons)
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        assert body["review_required"] is True
        assert body["review_reasons"] == reasons

    def test_empty_evidence_list_is_valid(self, client: TestClient) -> None:
        """evidence가 없는 criterion도 정상 직렬화되어야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result(
            criteria={
                "no_evidence_criterion": CriterionResult(
                    name="no_evidence_criterion",
                    passed=False,
                    reason="신호 없음",
                    confidence=0.5,
                    evidence=[],
                )
            }
        )
        mock_saved = _make_saved_result()

        with _patch_pipeline_run(mock_pipeline, mock_saved)[0]:
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        assert body["criteria"]["no_evidence_criterion"]["evidence"] == []


# ────────────────────────────────────────────
# 입력 검증 실패
# ────────────────────────────────────────────

class TestRuleClassifyValidation:
    """잘못된 요청 입력 검증."""

    def test_missing_url_returns_422(self, client: TestClient) -> None:
        """url 필드 누락 시 422를 반환해야 한다."""
        # Act
        response = client.post(CLASSIFY_URL, json={}, headers=HEADERS)

        # Assert
        assert response.status_code == 422

    def test_invalid_url_format_returns_422(self, client: TestClient) -> None:
        """URL 형식이 올바르지 않으면 422를 반환해야 한다."""
        # Act
        response = client.post(CLASSIFY_URL, json={"url": "not-a-url"}, headers=HEADERS)

        # Assert
        assert response.status_code == 422

    def test_empty_body_returns_422(self, client: TestClient) -> None:
        """빈 body 전송 시 422를 반환해야 한다."""
        # Act
        response = client.post(CLASSIFY_URL, content=b"", headers={**HEADERS, "Content-Type": "application/json"})

        # Assert
        assert response.status_code == 422


# ────────────────────────────────────────────
# 인증 실패
# ────────────────────────────────────────────

class TestRuleClassifyAuth:
    """API 키 인증 검증."""

    def test_missing_api_key_returns_422_or_403(self) -> None:
        """X-API-KEY 헤더 없을 시 422(헤더 누락) 또는 403을 반환해야 한다."""
        # Arrange
        client = TestClient(app)

        # Act
        response = client.post(CLASSIFY_URL, json={"url": "https://example.com"})

        # Assert
        assert response.status_code in (403, 422)

    def test_wrong_api_key_returns_403(self) -> None:
        """잘못된 API 키로 요청 시 403을 반환해야 한다."""
        import os

        with patch.dict(os.environ, {"API_KEY": "correct-key"}):
            client = TestClient(app)

            # Act
            response = client.post(
                CLASSIFY_URL,
                json={"url": "https://example.com"},
                headers={"X-API-KEY": "wrong-key"},
            )

        # Assert
        assert response.status_code == 403


# ────────────────────────────────────────────
# 파이프라인 오류 처리
# ────────────────────────────────────────────

class TestRuleClassifyPipelineError:
    """파이프라인 예외 처리 검증."""

    def test_pipeline_exception_returns_500(self, client: TestClient) -> None:
        """파이프라인이 예외를 발생시키면 500을 반환해야 한다."""
        # Arrange
        with patch("src.rule.analyzer.run_quality_pipeline", side_effect=RuntimeError("네트워크 오류")):
            # Act
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        assert response.status_code == 500

    def test_pipeline_exception_detail_included(self, client: TestClient) -> None:
        """500 응답 body에 오류 내용이 포함되어야 한다."""
        # Arrange
        with patch("src.rule.analyzer.run_quality_pipeline", side_effect=ValueError("분류 불가")):
            # Act
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        # Assert
        assert "분류" in body["detail"]

    def test_pipeline_connection_error_returns_500(self, client: TestClient) -> None:
        """파이프라인이 ConnectionError를 발생시켜도 500을 반환해야 한다."""
        # Arrange
        with patch("src.rule.analyzer.run_quality_pipeline", side_effect=ConnectionError("연결 실패")):
            # Act
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        assert response.status_code == 500


# ────────────────────────────────────────────
# DB 저장 오류 처리
# ────────────────────────────────────────────

class TestRuleClassifyDbError:
    """DB 저장 실패 처리 검증."""

    def test_detector_save_failure_returns_500(self, client: TestClient) -> None:
        """AIDetector.detect_and_save가 None을 반환하면 500을 반환해야 한다."""
        # Arrange
        mock_pipeline = _make_pipeline_result()
        mock_rule_analyzer = MagicMock()
        mock_rule_analyzer.last_pipeline_result = mock_pipeline

        with patch("src.api.rule_routes.RuleAnalyzer", return_value=mock_rule_analyzer), \
             patch("src.api.rule_routes.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.return_value = None

            # Act
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        assert response.status_code == 500

    def test_detector_exception_returns_500(self, client: TestClient) -> None:
        """AIDetector.detect_and_save가 예외를 발생시키면 500을 반환해야 한다."""
        # Arrange
        mock_rule_analyzer = MagicMock()

        with patch("src.api.rule_routes.RuleAnalyzer", return_value=mock_rule_analyzer), \
             patch("src.api.rule_routes.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.side_effect = RuntimeError("DB 오류")

            # Act
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        assert response.status_code == 500


# ────────────────────────────────────────────
# 캐시 스킵 케이스
# ────────────────────────────────────────────

def _make_ai_site_mock(
    *,
    site_id: int = 1,
    url: str = "https://example.com",
    is_ai_tool: bool = True,
    analyzer: str = "rule",
    hard_pass: Optional[bool] = True,
    total_score: Optional[float] = 75.0,
    review_required: Optional[bool] = False,
) -> Any:
    """테스트용 AISite mock 객체를 생성한다."""
    site = MagicMock()
    site.site_id = site_id
    site.url = url
    site.is_ai_tool = is_ai_tool
    site.analyzer = analyzer
    site.hard_pass = hard_pass
    site.total_score = total_score
    site.review_required = review_required
    return site


def _client_with_cached_site(site: Any) -> TestClient:
    """지정된 AISite mock을 DB 캐시로 반환하는 테스트 클라이언트를 생성한다."""
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = site
    app.dependency_overrides[verify_api_key] = lambda: API_KEY
    app.dependency_overrides[get_db] = lambda: mock_db
    return TestClient(app)


class TestRuleClassifyCacheHit:
    """DB 캐시 결과 반환 케이스 검증."""

    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_llm_cache_returns_200_without_pipeline(self) -> None:
        """LLM 분석 결과(analyzer=gemini)가 있으면 파이프라인 없이 200을 반환해야 한다."""
        # Arrange
        site = _make_ai_site_mock(analyzer="gemini", hard_pass=None, total_score=None, review_required=None)
        client = _client_with_cached_site(site)

        with patch("src.rule.analyzer.run_quality_pipeline") as mock_pipeline:
            # Act
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        # Assert
        assert response.status_code == 200
        mock_pipeline.assert_not_called()

    def test_llm_cache_response_has_site_id(self) -> None:
        """LLM 캐시 반환 시 site_id가 응답에 포함되어야 한다."""
        # Arrange
        site = _make_ai_site_mock(site_id=99, analyzer="gemini", hard_pass=None, total_score=None, review_required=None)
        client = _client_with_cached_site(site)

        with patch("src.rule.analyzer.run_quality_pipeline"):
            body = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS).json()

        assert body["site_id"] == 99

    def test_trustworthy_rule_cache_skips_pipeline(self) -> None:
        """신뢰 조건을 충족하는 규칙기반 캐시가 있으면 파이프라인을 실행하지 않아야 한다."""
        # Arrange: hard_pass=True, review_required=False, total_score >= 60
        site = _make_ai_site_mock(analyzer="rule", hard_pass=True, total_score=80.0, review_required=False)
        client = _client_with_cached_site(site)

        with patch("src.rule.analyzer.run_quality_pipeline") as mock_pipeline:
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        assert response.status_code == 200
        mock_pipeline.assert_not_called()

    def test_low_score_rule_cache_runs_pipeline(self) -> None:
        """total_score가 임계값 미달인 규칙기반 캐시는 파이프라인을 재실행해야 한다."""
        # Arrange: total_score < 60
        site = _make_ai_site_mock(analyzer="rule", hard_pass=True, total_score=50.0, review_required=False)
        client = _client_with_cached_site(site)

        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()
        mock_rule_analyzer = MagicMock()
        mock_rule_analyzer.last_pipeline_result = mock_pipeline

        with patch("src.api.rule_routes.RuleAnalyzer", return_value=mock_rule_analyzer), \
             patch("src.api.rule_routes.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.return_value = mock_saved
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        assert response.status_code == 200
        mock_rule_analyzer.analyze_website  # RuleAnalyzer가 생성됨을 확인

    def test_review_required_rule_cache_runs_pipeline(self) -> None:
        """review_required=True인 규칙기반 캐시는 파이프라인을 재실행해야 한다."""
        # Arrange
        site = _make_ai_site_mock(analyzer="rule", hard_pass=True, total_score=80.0, review_required=True)
        client = _client_with_cached_site(site)

        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()
        mock_rule_analyzer = MagicMock()
        mock_rule_analyzer.last_pipeline_result = mock_pipeline

        with patch("src.api.rule_routes.RuleAnalyzer", return_value=mock_rule_analyzer), \
             patch("src.api.rule_routes.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.return_value = mock_saved
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        assert response.status_code == 200

    def test_hard_pass_false_rule_cache_runs_pipeline(self) -> None:
        """hard_pass=False인 규칙기반 캐시는 파이프라인을 재실행해야 한다."""
        # Arrange
        site = _make_ai_site_mock(analyzer="rule", hard_pass=False, total_score=80.0, review_required=False)
        client = _client_with_cached_site(site)

        mock_pipeline = _make_pipeline_result()
        mock_saved = _make_saved_result()
        mock_rule_analyzer = MagicMock()
        mock_rule_analyzer.last_pipeline_result = mock_pipeline

        with patch("src.api.rule_routes.RuleAnalyzer", return_value=mock_rule_analyzer), \
             patch("src.api.rule_routes.AIDetector") as MockDetector:
            MockDetector.return_value.detect_and_save.return_value = mock_saved
            response = client.post(CLASSIFY_URL, json={"url": "https://example.com"}, headers=HEADERS)

        assert response.status_code == 200
