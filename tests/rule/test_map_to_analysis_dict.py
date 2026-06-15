"""
기능 3: _map_to_analysis_dict 변환 규칙 검증 테스트.

EvaluationResult → 분석 dict 변환 로직의 6가지 핵심 케이스를 검증한다.
"""

from __future__ import annotations

from typing import Dict


from src.rule.analyzer import _map_to_analysis_dict
from src.rule.models import CriterionResult, EvaluationResult


def _make_criterion(name: str, passed: bool, confidence: float = 1.0) -> CriterionResult:
    """테스트용 CriterionResult를 생성하는 헬퍼."""
    return CriterionResult(name=name, passed=passed, reason="테스트", confidence=confidence)


def _make_result(
    scope_decision: str = "ai",
    ai_confidence: float = 0.9,
    total_score: float | None = 80.0,
    taxonomy: Dict | None = None,
    criteria: Dict | None = None,
    homepage_title: str = "TestTool",
    input_url: str = "https://example.com",
) -> EvaluationResult:
    """테스트용 EvaluationResult를 생성하는 헬퍼."""
    if taxonomy is None:
        taxonomy = {
            "primary_category": "Coding",
            "taxonomy_skipped": False,
            "one_line_summary": "AI coding tool",
            "sub_tasks": ["코드 생성", "코드 리뷰", "버그 분석"],
        }
    if criteria is None:
        criteria = {
            "has_privacy_or_data_policy": _make_criterion("has_privacy_or_data_policy", True, 0.95),
        }
    extracted: Dict = {
        "ai_scope": {
            "scope_decision": scope_decision,
            "confidence": ai_confidence,
        },
        "taxonomy": taxonomy,
        "homepage_title": homepage_title,
    }
    return EvaluationResult(
        input_url=input_url,
        normalized_url=input_url,
        predicted_status="incubating",
        final_status="incubating",
        passed_count=3,
        hard_pass=True,
        review_required=False,
        review_reasons=[],
        criteria=criteria,
        summary="테스트 요약",
        extracted=extracted,
        total_score=total_score,
    )


class TestScopeDecisionMapping:
    """scope_decision 값에 따른 is_ai_tool 변환 검증."""

    def test_scope_decision_non_ai_returns_is_ai_tool_false(self) -> None:
        """scope_decision='non_ai'이면 is_ai_tool=False를 반환해야 한다."""
        # Arrange
        result = _make_result(scope_decision="non_ai")

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["is_ai_tool"] is False

    def test_scope_decision_uncertain_returns_is_ai_tool_true(self) -> None:
        """scope_decision='uncertain'이면 is_ai_tool=True를 반환해야 한다."""
        # Arrange
        result = _make_result(scope_decision="uncertain")

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["is_ai_tool"] is True

    def test_scope_decision_ai_returns_is_ai_tool_true(self) -> None:
        """scope_decision='ai'이면 is_ai_tool=True를 반환해야 한다."""
        # Arrange
        result = _make_result(scope_decision="ai")

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["is_ai_tool"] is True


class TestTaxonomySkipped:
    """taxonomy_skipped 값에 따른 categories 변환 검증."""

    def test_taxonomy_skipped_true_returns_empty_categories(self) -> None:
        """taxonomy_skipped=True이면 categories=[]를 반환해야 한다."""
        # Arrange
        taxonomy = {"taxonomy_skipped": True}
        result = _make_result(taxonomy=taxonomy)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["categories"] == []

    def test_taxonomy_skipped_false_returns_categories(self) -> None:
        """taxonomy_skipped=False이면 categories가 비어있지 않아야 한다."""
        # Arrange
        taxonomy = {
            "taxonomy_skipped": False,
            "primary_category": "Coding",
            "one_line_summary": "AI coding tool",
            "sub_tasks": [],
        }
        result = _make_result(taxonomy=taxonomy)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert len(analysis["categories"]) == 1
        assert analysis["categories"][0]["level_1"] == "code"
        assert analysis["categories"][0]["level_2"] == "code-generation"
        assert analysis["categories"][0]["is_primary"] is True


class TestScoreUtilityMapping:
    """total_score 값에 따른 scores.utility 변환 검증."""

    def test_total_score_50_returns_utility_5(self) -> None:
        """total_score=50.0이면 scores.utility=5를 반환해야 한다."""
        # Arrange
        result = _make_result(total_score=50.0)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["utility"] == 5

    def test_total_score_none_returns_utility_5(self) -> None:
        """total_score=None이면 scores.utility=5(기본값)를 반환해야 한다."""
        # Arrange
        result = _make_result(total_score=None)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["utility"] == 5

    def test_total_score_100_returns_utility_10(self) -> None:
        """total_score=100.0이면 scores.utility=10을 반환해야 한다."""
        # Arrange
        result = _make_result(total_score=100.0)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["utility"] == 10

    def test_total_score_0_returns_utility_1(self) -> None:
        """total_score=0이면 scores.utility=1(최소값 클램프)를 반환해야 한다."""
        # Arrange
        result = _make_result(total_score=0.0)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["utility"] == 1


class TestScoreTrustMapping:
    """has_privacy_or_data_policy.confidence 값에 따른 scores.trust 변환 검증."""

    def test_privacy_confidence_095_returns_trust_10(self) -> None:
        """confidence=0.95이면 scores.trust=10(round(9.5)=10)를 반환해야 한다."""
        # Arrange
        criteria = {
            "has_privacy_or_data_policy": _make_criterion("has_privacy_or_data_policy", True, 0.95),
        }
        result = _make_result(criteria=criteria)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["trust"] == 10

    def test_privacy_criterion_missing_returns_trust_5(self) -> None:
        """has_privacy_or_data_policy criterion이 없으면 scores.trust=5(기본값)를 반환해야 한다."""
        # Arrange
        result = _make_result(criteria={})

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["trust"] == 5

    def test_originality_always_5(self) -> None:
        """scores.originality는 항상 고정값 5를 반환해야 한다."""
        # Arrange
        result = _make_result()

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["scores"]["originality"] == 5


class TestRequiredFields:
    """반환 dict의 필수 필드 존재 및 타입 검증."""

    def test_all_required_fields_present(self) -> None:
        """is_ai_tool, title, description, confidence 4개 필수 필드가 모두 존재해야 한다."""
        # Arrange
        result = _make_result()

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        for field in ["is_ai_tool", "title", "description", "confidence"]:
            assert field in analysis, f"필수 필드 누락: {field}"

    def test_analyzer_value_is_rule(self) -> None:
        """analyzer 필드가 'rule' 고정값을 반환해야 한다."""
        # Arrange
        result = _make_result()

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["analyzer"] == "rule"

    def test_confidence_range_is_0_to_1(self) -> None:
        """confidence 값이 0.0–1.0 범위 내에 있어야 한다."""
        # Arrange
        result = _make_result(ai_confidence=0.88)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert 0.0 <= analysis["confidence"] <= 1.0

    def test_title_is_not_empty(self) -> None:
        """title 값이 빈 문자열이 아니어야 한다."""
        # Arrange
        result = _make_result(homepage_title="TestTool")

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert analysis["title"] != ""

    def test_title_falls_back_to_host_when_no_homepage_title(self) -> None:
        """homepage_title이 없으면 URL 호스트명으로 폴백해야 한다."""
        # Arrange
        result = _make_result(homepage_title="", input_url="https://mytool.ai")
        result.extracted["homepage_title"] = ""

        # Act
        analysis = _map_to_analysis_dict(result, "https://mytool.ai")

        # Assert
        assert "mytool.ai" in analysis["title"]

    def test_tags_max_3_items(self) -> None:
        """tags는 최대 3개 항목만 반환해야 한다."""
        # Arrange
        taxonomy = {
            "taxonomy_skipped": False,
            "primary_category": "Coding",
            "one_line_summary": "test",
            "sub_tasks": ["a", "b", "c", "d", "e"],
        }
        result = _make_result(taxonomy=taxonomy)

        # Act
        analysis = _map_to_analysis_dict(result, "https://example.com")

        # Assert
        assert len(analysis["tags"]) <= 3
