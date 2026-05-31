"""
리뷰 게이트 정책을 제공하는 모듈.
"""

from __future__ import annotations


from src.rule.models import CriterionResult, FetchResult


class StatusPolicyMixin:
    """리뷰 게이트 정책을 제공하는 믹스인."""

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
