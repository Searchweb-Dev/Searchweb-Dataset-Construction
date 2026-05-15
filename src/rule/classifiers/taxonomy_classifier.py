"""
수집 텍스트를 바탕으로 카테고리/태그 taxonomy를 분류하는 모듈.
"""

from __future__ import annotations

import re
import logging
from typing import Any

from src.rule.keywords import (
    DEFAULT_META_BY_PRIMARY,
    META_CATEGORY_KEYWORDS,
    PLATFORM_KEYWORDS,
    PRICE_VALUE_RE,
    PRIMARY_CATEGORY_KEYWORDS,
    SUBTASK_KEYWORDS_BY_PRIMARY,
)
from src.rule.models import FetchResult
from src.rule.utils import keyword_hit, keyword_hit_count, lower, snippet, split_sentences

logger = logging.getLogger(__name__)


class TaxonomyClassifierMixin:
    """수집 텍스트를 기반으로 taxonomy를 분류하는 믹스인."""

    def _classify_taxonomy(
        self,
        homepage: FetchResult,
        all_pages: dict[str, FetchResult],
        extracted: dict[str, object],
        text_cache: dict[str, str] | None = None,
    ) -> dict[str, object]:
        """본문/메타/링크 텍스트 기반으로 taxonomy(카테고리/태그)를 분류한다."""
        usable_pages = [p for p in all_pages.values() if p.ok]
        if text_cache:
            corpus = str(text_cache.get("corpus", "")).strip()
            header_blob = str(text_cache.get("header_blob", "")).strip()
            links_blob = str(text_cache.get("links_blob", "")).strip()
            combined_blob = str(text_cache.get("combined_blob", "")).strip()
        else:
            corpus = ""
            header_blob = ""
            links_blob = ""
            combined_blob = ""
        if not combined_blob:
            page_blobs = [" ".join([p.final_url, p.title, p.meta_description, p.text[:5000]]) for p in usable_pages]
            header_blobs = [" ".join([p.final_url, p.title, p.meta_description]) for p in usable_pages]
            link_blobs = [f"{t} {u}" for p in usable_pages for t, u in p.links[:80]]
            corpus = lower(" ".join(page_blobs))
            header_blob = lower(" ".join(header_blobs))
            links_blob = lower(" ".join(link_blobs))
            combined_blob = " ".join([corpus, header_blob, links_blob])
        ai_scope = extracted.get("ai_scope", {})
        scope_decision = str(ai_scope.get("scope_decision", "")).lower() if isinstance(ai_scope, dict) else ""
        is_ai_site = bool(ai_scope.get("is_ai_site", True)) if isinstance(ai_scope, dict) else True

        if scope_decision == "non_ai" or (not scope_decision and not is_ai_site):
            return {
                "is_ai_site": False,
                "scope_decision": "non_ai",
                "ai_site_confidence": ai_scope.get("confidence", 0.0) if isinstance(ai_scope, dict) else 0.0,
                "ai_site_reason": ai_scope.get("reason", "AI 사이트 아님") if isinstance(ai_scope, dict) else "AI 사이트 아님",
                "ai_keyword_hits": ai_scope.get("ai_keyword_hits", []) if isinstance(ai_scope, dict) else [],
                "non_ai_keyword_hits": ai_scope.get("non_ai_keyword_hits", []) if isinstance(ai_scope, dict) else [],
                "taxonomy_skipped": True,
            }

        category_scores: dict[str, float] = {}
        for category, keywords in PRIMARY_CATEGORY_KEYWORDS.items():
            body_hits = keyword_hit_count(corpus, keywords, normalized=True)
            header_hits = keyword_hit_count(header_blob, keywords, normalized=True)
            link_hits = keyword_hit_count(links_blob, keywords, normalized=True)
            category_scores[category] = body_hits + (1.5 * header_hits) + (0.7 * link_hits)

        ranked_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)
        top_category, top_score = ranked_categories[0] if ranked_categories else ("Uncategorized", 0.0)
        second_score = ranked_categories[1][1] if len(ranked_categories) > 1 else 0.0

        domain = (re.sub(r"^https?://", "", homepage.final_url or homepage.url)).split("/")[0]
        logger.debug("[%s] Taxonomy 점수 상세: %s", domain, ranked_categories[:3])

        if top_score < 1.0:
            primary_category = "Uncategorized"
            primary_confidence = 0.0
            logger.info("[%s] Taxonomy 분류 실패: 매칭 점수 부족(top_score=%.1f)", domain, top_score)
        else:
            primary_category = top_category
            margin = max(0.0, top_score - second_score)
            primary_confidence = min(0.99, 0.42 + min(top_score, 8.0) * 0.06 + min(margin, 5.0) * 0.05)
            logger.info("[%s] Taxonomy 분류 성공: %s (score=%.1f, conf=%.2f)",
                        domain, primary_category, top_score, primary_confidence)

        subtask_scores: dict[str, int] = {}
        for subtask, keywords in SUBTASK_KEYWORDS_BY_PRIMARY.get(primary_category, {}).items():
            hits = keyword_hit_count(combined_blob, keywords, normalized=True)
            if hits > 0:
                subtask_scores[subtask] = hits
        max_sub_tasks = max(1, int(getattr(self.config, "max_sub_tasks", 5)))
        sub_tasks = [
            name
            for name, _ in sorted(subtask_scores.items(), key=lambda x: x[1], reverse=True)[:max_sub_tasks]
        ]

        meta_scores: dict[str, int] = {}
        for meta, keywords in META_CATEGORY_KEYWORDS.items():
            hits = keyword_hit_count(combined_blob, keywords, normalized=True)
            if hits > 0:
                meta_scores[meta] = hits
        meta_categories = [name for name, _ in sorted(meta_scores.items(), key=lambda x: x[1], reverse=True)[:3]]
        if not meta_categories and primary_category in DEFAULT_META_BY_PRIMARY:
            meta_categories = DEFAULT_META_BY_PRIMARY[primary_category][:2]

        if homepage.meta_description and len(homepage.meta_description) >= 20:
            one_line_summary = snippet(homepage.meta_description, max_len=180)
        else:
            sentence_candidates = split_sentences(homepage.text[:1600])
            one_line_summary = snippet(sentence_candidates[0], max_len=180) if sentence_candidates else snippet(homepage.title or homepage.text, max_len=180)

        has_api = keyword_hit(combined_blob, PLATFORM_KEYWORDS["api"]) or any("/api" in p.final_url.lower() for p in usable_pages)
        platforms = self._infer_platforms(combined_blob, has_api, usable_pages)
        pricing_model = self._infer_pricing_model(combined_blob, extracted)

        return {
            "primary_category": primary_category,
            "primary_confidence": round(primary_confidence, 3),
            "category_scores": {k: round(v, 2) for k, v in ranked_categories},
            "sub_tasks": sub_tasks,
            "meta_categories": meta_categories,
            "one_line_summary": one_line_summary,
            "has_api": has_api,
            "pricing_model": pricing_model,
            "platforms": platforms,
            "is_ai_site": True if scope_decision != "non_ai" else False,
            "scope_decision": scope_decision or ("ai" if is_ai_site else "non_ai"),
            "ai_site_confidence": ai_scope.get("confidence", 1.0) if isinstance(ai_scope, dict) else 1.0,
            "ai_site_reason": ai_scope.get("reason", "AI 사이트로 판정됨") if isinstance(ai_scope, dict) else "AI 사이트로 판정됨",
            "ai_keyword_hits": ai_scope.get("ai_keyword_hits", []) if isinstance(ai_scope, dict) else [],
            "non_ai_keyword_hits": ai_scope.get("non_ai_keyword_hits", []) if isinstance(ai_scope, dict) else [],
            "taxonomy_skipped": False,
        }

    def _infer_pricing_model(self, text_blob: str, extracted: dict[str, object]) -> str:
        """텍스트 신호와 추출 결과를 바탕으로 pricing model 타입을 추정한다."""
        if bool(extracted.get("license_detected")):
            return "open_source_license"
        has_contact_sales = any(k in text_blob for k in ["contact sales", "request a demo", "문의하기"])
        has_free = any(k in text_blob for k in ["free", "free trial", "free tier", "무료", "체험"])
        has_paid = bool(PRICE_VALUE_RE.search(text_blob)) or any(k in text_blob for k in ["monthly", "annual", "subscription", "pricing", "요금", "구독"])
        if has_free and has_paid:
            return "free_and_paid"
        if has_paid and has_contact_sales:
            return "paid_plus_contact_sales"
        if has_paid:
            return "paid"
        if has_contact_sales:
            return "contact_sales_only"
        if has_free:
            return "free"
        return "unknown"

    def _platform_keyword_hit_count(self, text_blob: str, keywords: set) -> int:
        """플랫폼 키워드 집합이 본문에서 실제로 몇 개 매칭되는지 계산한다."""
        count = 0
        for raw_keyword in keywords:
            keyword = lower(raw_keyword)
            if not keyword:
                continue
            if len(keyword) <= 4 and keyword.isalpha():
                pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
                if re.search(pattern, text_blob):
                    count += 1
                continue
            if keyword in text_blob:
                count += 1
        return count

    def _infer_platforms(self, text_blob: str, has_api: bool, pages: list[FetchResult]) -> list[str]:
        """플랫폼 키워드/URL 신호를 결합해 지원 플랫폼 목록을 추정한다."""
        normalized_blob = lower(text_blob)
        found: set = set()

        if pages:
            found.add("web")

        for platform, keywords in PLATFORM_KEYWORDS.items():
            if platform == "api":
                continue
            hit_count = self._platform_keyword_hit_count(normalized_blob, keywords)
            if hit_count > 0:
                found.add(platform)

        url_blob = lower(" ".join(p.final_url for p in pages))
        if any(host_hint in url_blob for host_hint in ["apps.apple.com", "play.google.com", "appstore", "googleplay"]):
            found.add("mobile")
        if any(ext_hint in url_blob for ext_hint in ["chromewebstore.google.com", "addons.mozilla.org", "microsoftedge.microsoft.com/addons"]):
            found.add("browser_extension")
        if any(desktop_hint in url_blob for desktop_hint in ["/download", "/desktop", "macos", "windows"]):
            found.add("desktop")

        if has_api:
            found.add("api")

        platform_order = [
            "web",
            "mobile",
            "desktop",
            "browser_extension",
            "slack",
            "vscode",
            "api",
        ]
        return [name for name in platform_order if name in found]
