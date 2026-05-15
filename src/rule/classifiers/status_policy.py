"""
상태 예측, 리뷰 게이트, 요약 생성 정책을 제공하는 모듈.
"""

from __future__ import annotations


from src.rule.models import CriterionResult, FetchResult


class StatusPolicyMixin:
    """상태 예측, 리뷰 게이트, 요약 생성 정책을 제공하는 믹스인."""

    def _build_score_context(self, criteria: dict[str, CriterionResult]) -> dict[str, object]:
        """점수기반 평가기에서 override 가능한 점수 컨텍스트를 생성한다."""
        return {}

    def _predict_status(
        self,
        criteria: dict[str, CriterionResult],
        passed_count: int,
        hard_pass: bool,
        score_context: dict[str, object],
    ) -> str:
        """규칙 기반 기본 상태(curated/incubating/rejected)를 예측한다."""
        if not hard_pass:
            return "rejected"
        if passed_count >= self.config.min_curated_count:
            return "curated"
        if passed_count == self.config.incubating_count:
            return "incubating"
        return "rejected"

    def _review_gate(
        self,
        criteria: dict[str, CriterionResult],
        homepage: FetchResult,
        extracted: dict[str, object],
        predicted_status: str,
    ) -> tuple[bool, list[str]]:
        """수동 검토 필요 여부와 사유 목록을 결정한다."""
        if any(result.reason.startswith("AI 사이트 판별 게이트에서 제외됨") for result in criteria.values()):
            return (False, [])

        reasons: list[str] = []
        ai_scope = extracted.get("ai_scope", {})
        if isinstance(ai_scope, dict) and str(ai_scope.get("scope_decision", "")).lower() == "uncertain":
            reasons.append("AI 사이트 판정이 경계 구간(uncertain)으로 수동 확인이 필요함")
        if criteria["clear_function_desc"].confidence < 0.75:
            reasons.append("기능 설명 판정 신뢰도가 낮음")
        if extracted.get("contact_sales_only"):
            reasons.append("문의 기반 가격 정책으로 보임")
        if extracted.get("faq_only_docs"):
            reasons.append("FAQ만 존재하고 정식 docs/help center 여부가 애매함")
        if bool(extracted.get("anti_bot_blocked")):
            reasons.append("anti-bot/challenge 응답으로 인해 신뢰 가능한 본문 수집이 제한됨")
        fetcher = getattr(self, "fetcher", None)
        playwright_enabled = bool(extracted.get("playwright_enabled", True))
        if homepage.fetched_by == "requests" and self.config.use_playwright and playwright_enabled:
            thin_content = (
                len(homepage.text or "") < self.config.min_text_len_for_static_success
                or len(homepage.links or []) < self.config.min_links_for_static_success
            )
            if bool(extracted.get("anti_bot_blocked")) or thin_content:
                reasons.append("Playwright 재수집 없이 requests 결과만 사용됨")
        if predicted_status == "curated":
            if not criteria["has_docs_or_help"].passed:
                reasons.append("curated 근거로 사용할 docs/help evidence가 부족함")
            if not criteria["has_privacy_or_data_policy"].passed:
                reasons.append("curated 근거로 사용할 policy evidence가 부족함")
        return (len(reasons) > 0, reasons)

    def _build_summary(
        self,
        criteria: dict[str, CriterionResult],
        predicted_status: str,
        final_status: str,
        passed_count: int,
        review_required: bool,
        review_reasons: list[str],
        score_context: dict[str, object],
    ) -> str:
        """평가 결과를 사람이 읽기 쉬운 요약 문자열로 생성한다."""
        passed_names = [name for name, result in criteria.items() if result.passed]
        failed_names = [name for name, result in criteria.items() if not result.passed]
        text = (
            f"총 {passed_count}/5개 기준 충족. "
            f"예상 상태={predicted_status}, 최종 상태={final_status}. "
            f"통과 항목={passed_names}, 미통과 항목={failed_names}."
        )
        non_ai_scope_reason = next(
            (
                result.reason
                for result in criteria.values()
                if result.reason.startswith("AI 사이트 판별 게이트에서 제외됨")
            ),
            "",
        )
        if non_ai_scope_reason:
            text += f" 비대상 처리 사유={non_ai_scope_reason}."
        if review_required:
            text += f" 수동 검수 필요 사유={review_reasons}."
        return text
