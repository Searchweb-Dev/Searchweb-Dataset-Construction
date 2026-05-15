"""
평가 대상이 AI 사이트인지 판정하는 스코프 게이트 모듈.
"""

from __future__ import annotations

import re
import logging

from src.rule.keywords import (
    AI_SITE_STRONG_KEYWORDS,
    AI_SITE_WEAK_KEYWORDS,
    NON_AI_SITE_STRONG_KEYWORDS,
    NON_AI_SITE_WEAK_KEYWORDS,
)
from src.rule.models import FetchResult
from src.rule.utils import get_domain, lower

logger = logging.getLogger(__name__)


class AiScopeClassifierMixin:
    """수집 텍스트를 기반으로 AI 사이트 여부를 판정하는 믹스인."""

    def _classify_ai_scope(
        self,
        homepage: FetchResult,
        all_pages: dict[str, FetchResult],
        text_cache: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """페이지 텍스트/링크를 결합해 AI 사이트 판정 결과를 반환한다."""
        combined_blob = ""
        if text_cache:
            combined_blob = str(text_cache.get("ai_scope_blob", "")).strip()
        if not combined_blob:
            usable_pages = [p for p in all_pages.values() if p.ok]
            page_blobs = [" ".join([p.final_url, p.title, p.meta_description, p.text[:5000]]) for p in usable_pages]
            link_blobs = [f"{t} {u}" for p in usable_pages for t, u in p.links[:80]]
            combined_blob = lower(" ".join(page_blobs + link_blobs))
        return self._infer_ai_site_scope(combined_blob, homepage)

    def _infer_ai_site_scope(self, text_blob: str, homepage: FetchResult) -> dict[str, object]:
        """수집 텍스트를 기반으로 평가 대상이 AI 사이트인지 판별한다."""
        normalized_blob = lower(text_blob)
        strong_ai_hits = self._collect_keyword_hits(normalized_blob, AI_SITE_STRONG_KEYWORDS)
        weak_ai_hits = self._collect_keyword_hits(normalized_blob, AI_SITE_WEAK_KEYWORDS)
        strong_non_ai_hits = self._collect_keyword_hits(normalized_blob, NON_AI_SITE_STRONG_KEYWORDS)
        weak_non_ai_hits = self._collect_keyword_hits(normalized_blob, NON_AI_SITE_WEAK_KEYWORDS)
        non_ai_hits = strong_non_ai_hits | weak_non_ai_hits
        if re.search(r"(?<![a-z0-9])ai(?![a-z0-9])", normalized_blob):
            weak_ai_hits.add("ai")

        ai_hits = strong_ai_hits | weak_ai_hits
        explicit_ai_weak_hits = {
            k
            for k in weak_ai_hits
            if k in {"ai", "ai assistant", "ai agent"}
        }
        ai_signal_score = (2 * len(strong_ai_hits)) + len(weak_ai_hits)
        non_ai_signal_score = (2 * len(strong_non_ai_hits)) + len(weak_non_ai_hits)
        ai_non_ai_margin = ai_signal_score - non_ai_signal_score

        domain = get_domain(homepage.final_url or homepage.url)
        logger.debug("[%s] AI Scope 계산: ai_score=%d, non_ai_score=%d, margin=%d",
                     domain, ai_signal_score, non_ai_signal_score, ai_non_ai_margin)

        uncertain_margin_low = int(getattr(self.config, "ai_scope_uncertain_margin_low", -1))
        uncertain_margin_high = int(getattr(self.config, "ai_scope_uncertain_margin_high", 2))
        uncertain_non_ai_score_cap = int(getattr(self.config, "ai_scope_uncertain_non_ai_score_cap", 6))

        known_ai_brand_hint = any(
            token in domain
            for token in [
                "openai",
                "anthropic",
                "huggingface",
                "perplexity",
                "midjourney",
                "stability",
                "mistral",
                "cohere",
            ]
        )
        tld_ai_hint = domain.endswith(".ai")

        if len(strong_ai_hits) >= 2 and ai_non_ai_margin >= 1:
            decision = "ai"
            reason = f"강한 AI 신호 {len(strong_ai_hits)}개와 양수 마진을 확인함"
        elif len(strong_ai_hits) >= 1 and (len(weak_ai_hits) >= 1 or ai_non_ai_margin >= 1) and non_ai_signal_score <= 4:
            decision = "ai"
            reason = "강한 AI 신호와 보조 신호를 함께 확인함"
        elif (
            len(strong_ai_hits) == 0
            and len(explicit_ai_weak_hits) >= 1
            and len(weak_ai_hits) >= 3
            and ai_non_ai_margin >= 3
            and non_ai_signal_score <= 1
        ):
            decision = "ai"
            reason = "약한 AI 신호가 다수이며 비AI 신호 대비 우세함"
        elif known_ai_brand_hint and (len(strong_ai_hits) >= 1 or ai_non_ai_margin >= 1 or non_ai_signal_score <= 3):
            decision = "ai"
            reason = "AI 브랜드 도메인 신호가 확인됨"
        elif tld_ai_hint and (len(strong_ai_hits) >= 1 or (len(weak_ai_hits) >= 2 and non_ai_signal_score <= 2)):
            decision = "ai"
            reason = ".ai 도메인과 AI 콘텐츠 신호를 확인함"
        elif (
            (ai_signal_score > 0 and uncertain_margin_low <= ai_non_ai_margin <= uncertain_margin_high and non_ai_signal_score <= uncertain_non_ai_score_cap)
            or (known_ai_brand_hint and ai_signal_score == 0 and non_ai_signal_score <= uncertain_non_ai_score_cap + 1)
        ):
            decision = "uncertain"
            reason = "AI 판정 점수가 경계 구간에 있어 수동 검토가 필요함"
        else:
            decision = "non_ai"
            reason = "AI 신호 대비 일반 콘텐츠 신호가 우세하거나 강한 AI 신호가 부족함"

        logger.info("[%s] AI Scope 판정 결과: %s (사유: %s)", domain, decision, reason)

        is_ai_site = decision != "non_ai"
        is_uncertain = decision == "uncertain"

        if decision == "ai":
            confidence = 0.97 if len(strong_ai_hits) >= 2 else 0.88
        elif decision == "uncertain":
            confidence = 0.62
        else:
            confidence = 0.96 if ai_signal_score == 0 else (0.9 if ai_non_ai_margin <= -2 else 0.82)

        return {
            "is_ai_site": is_ai_site,
            "scope_decision": decision,
            "is_uncertain": is_uncertain,
            "requires_review": is_uncertain,
            "confidence": confidence,
            "reason": reason,
            "ai_keyword_hits": sorted(ai_hits)[:8],
            "strong_ai_keyword_hits": sorted(strong_ai_hits)[:8],
            "weak_ai_keyword_hits": sorted(weak_ai_hits)[:8],
            "non_ai_keyword_hits": sorted(non_ai_hits)[:8],
            "strong_non_ai_keyword_hits": sorted(strong_non_ai_hits)[:8],
            "weak_non_ai_keyword_hits": sorted(weak_non_ai_hits)[:8],
            "ai_signal_score": ai_signal_score,
            "non_ai_signal_score": non_ai_signal_score,
            "ai_non_ai_margin": ai_non_ai_margin,
        }

    def _collect_keyword_hits(self, text_blob: str, keywords: set) -> set:
        """키워드 집합 중 매칭된 항목을 반환한다."""
        hits: set = set()
        for raw_keyword in keywords:
            keyword = lower(raw_keyword)
            if not keyword:
                continue
            if keyword.isalpha():
                pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
                if re.search(pattern, text_blob):
                    hits.add(raw_keyword)
                continue
            if keyword in text_blob:
                hits.add(raw_keyword)
        return hits
