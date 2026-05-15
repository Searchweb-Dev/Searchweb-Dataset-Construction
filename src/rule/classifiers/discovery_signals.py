"""
후보 URL 수집과 구조화 신호(extracted) 추출을 담당하는 모듈.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from src.rule.config import EvalConfig
from src.rule.keywords import DOCS_TEXT, NEGATIVE_USE_TEXT, POLICY_TEXT, POSITIVE_USE_TEXT
from src.rule.models import FetchResult
from src.rule.utils import (
    is_allowed_external_docs_link,
    is_allowed_external_policy_link,
    is_likely_pricing_link,
    is_same_domain,
    is_strong_pricing_page,
    keyword_hit,
    likely_related_external_candidates,
    lower,
    normalize_url,
)


class DiscoverySignalMixin:
    """후보 URL 수집과 구조화 신호 추출 기능을 제공하는 믹스인."""

    config: EvalConfig
    fetcher: object

    def _collect_candidate_urls(self, homepage_url: str, homepage: FetchResult) -> list[str]:
        """홈페이지 링크/fallback 규칙으로 후속 탐색 URL 후보를 구성한다."""
        kinds: dict[str, list[str]] = {"pricing": [], "docs": [], "policy": [], "product": [], "probe": []}
        seen_in_kind = {k: set() for k in kinds.keys()}

        def add_url(kind: str, u: str) -> None:
            """종류별 중복 없이 후보 URL을 추가한다."""
            nu = normalize_url(u)
            if nu in seen_in_kind[kind]:
                return
            seen_in_kind[kind].add(nu)
            kinds[kind].append(nu)

        def add_related_seed(u: str) -> None:
            """도메인 규칙 기반 외부 후보를 성격에 맞는 kind로 우선 배치한다."""
            parsed = urlparse(u)
            host = (parsed.netloc or "").lower()
            path = (parsed.path or "").lower()
            if any(seg in path for seg in ["/pricing", "/plans"]):
                add_url("pricing", u)
                return
            if any(seg in path for seg in ["/privacy", "/policy", "/terms", "/security"]):
                add_url("policy", u)
                return
            if host.startswith(("help.", "docs.", "support.", "developers.", "developer.")):
                add_url("docs", u)
                return
            if any(seg in path for seg in ["/help", "/docs", "/support", "/faq", "/guide", "/collections/"]):
                add_url("docs", u)
                return
            add_url("probe", u)

        if homepage.ok:
            for link_text, href in homepage.links:
                blob = lower(f"{link_text} {href}")
                same_domain = is_same_domain(homepage_url, href)
                if is_likely_pricing_link(link_text, href):
                    add_url("pricing", href)
                if same_domain and keyword_hit(blob, DOCS_TEXT):
                    add_url("docs", href)
                if (not same_domain) and is_allowed_external_docs_link(link_text, href):
                    add_url("docs", href)
                if same_domain and keyword_hit(blob, POLICY_TEXT):
                    add_url("policy", href)
                if (not same_domain) and is_allowed_external_policy_link(link_text, href):
                    add_url("policy", href)
                if same_domain and any(k in blob for k in ["product", "features", "how it works", "about", "use cases", "solutions", "platform", "기능", "소개", "사용 사례"]):
                    add_url("product", href)

        for seed in likely_related_external_candidates(homepage_url):
            add_related_seed(seed)

        estimated_collected = len(kinds["pricing"]) + len(kinds["docs"]) + len(kinds["policy"]) + len(kinds["product"])
        if (not homepage.ok) or estimated_collected < min(4, self.config.max_total_candidate_pages):
            for path in self.config.fallback_probe_paths:
                add_url("probe", urljoin(homepage_url, path))

        ordered: list[str] = []
        seen_global: set = set()

        def merge(urls: list[str], limit: int | None = None) -> None:
            """우선순위 순서로 URL을 합치면서 전역 중복과 최대 개수를 제어한다."""
            subset = urls if limit is None else urls[:limit]
            for u in subset:
                if u in seen_global:
                    continue
                seen_global.add(u)
                ordered.append(u)
                if len(ordered) >= self.config.max_total_candidate_pages:
                    return

        for kind in ["pricing", "docs", "policy", "product"]:
            merge(kinds[kind], self.config.max_candidate_pages_per_kind)
            if len(ordered) >= self.config.max_total_candidate_pages:
                return ordered[: self.config.max_total_candidate_pages]

        merge(kinds["probe"], None)
        return ordered[: self.config.max_total_candidate_pages]

    def _extract_structured_signals(self, homepage: FetchResult, pages: list[FetchResult]) -> dict[str, object]:
        """수집된 페이지들에서 pricing/docs/policy 등 구조화 신호를 추출한다."""
        page_map: dict[str, list[str]] = {"pricing_pages": [], "docs_pages": [], "policy_pages": [], "product_pages": []}
        faq_only_docs = False
        contact_sales_only = False
        license_detected = False
        update_signal = False

        for p in pages:
            if not p.ok:
                continue
            blob = lower(" ".join([p.final_url, p.title, p.meta_description, p.text[:3000]]))
            if is_strong_pricing_page(p.final_url, p.title, p.meta_description, p.text):
                page_map["pricing_pages"].append(p.final_url)
            url_title_blob = lower(" ".join([p.final_url, p.title, p.meta_description]))
            if keyword_hit(url_title_blob, DOCS_TEXT) or any(seg in lower(p.final_url) for seg in ["/docs", "/help", "/support", "/faq", "/guide"]):
                page_map["docs_pages"].append(p.final_url)
            if keyword_hit(url_title_blob, POLICY_TEXT) or any(seg in lower(p.final_url) for seg in ["/privacy", "/policy", "/terms", "/security"]):
                page_map["policy_pages"].append(p.final_url)
            if any(k in blob for k in ["feature", "how it works", "use case", "product", "platform", "solution", "기능", "사용 사례"]):
                page_map["product_pages"].append(p.final_url)

            if "faq" in blob and not any(k in blob for k in ["docs", "documentation", "guide", "quickstart", "getting started", "help center"]):
                faq_only_docs = True
            if ("contact sales" in blob or "request a demo" in blob or "문의하기" in blob) and not re.search(
                r"(\$|₩|무료|free|starter|pro|business|enterprise|usage|seat|monthly|annual|월|연)",
                blob,
            ):
                contact_sales_only = True
            if "license" in blob or "mit license" in blob or "apache 2.0" in blob or "gnu" in blob:
                license_detected = True
            if re.search(r"(changelog|release notes|what's new|updated on|last updated|릴리즈|업데이트)", blob):
                update_signal = True

        homepage_blob = lower(" ".join([homepage.title, homepage.meta_description, homepage.text[:2500]]))
        link_blob = lower(" ".join([f"{t} {u}" for t, u in homepage.links]))
        homepage_error = lower(homepage.error or "")
        challenge_probe_text = " ".join([homepage.final_url, homepage.title, homepage.text[:2500], homepage_error])
        challenge_detector = getattr(self.fetcher, "is_challenge_text", None)
        challenge_detected = bool(challenge_detector(challenge_probe_text)) if callable(challenge_detector) else False
        anti_bot_blocked = bool(
            "anti_bot_challenge_detected" in homepage_error
            or challenge_detected
        )

        fetcher = getattr(self, "fetcher", None)
        playwright_enabled = getattr(fetcher, "playwright_enabled", False)
        playwright_disabled_reason = getattr(fetcher, "playwright_disabled_reason", None)

        return {
            "homepage_accessible": homepage.ok,
            "homepage_final_url": homepage.final_url,
            "homepage_title": homepage.title,
            "has_waitlist_signal": keyword_hit(homepage_blob + " " + link_blob, NEGATIVE_USE_TEXT),
            "has_positive_use_signal": keyword_hit(homepage_blob + " " + link_blob, POSITIVE_USE_TEXT),
            "pricing_pages": list(dict.fromkeys(page_map["pricing_pages"])),
            "docs_pages": list(dict.fromkeys(page_map["docs_pages"])),
            "policy_pages": list(dict.fromkeys(page_map["policy_pages"])),
            "product_pages": list(dict.fromkeys(page_map["product_pages"])),
            "faq_only_docs": faq_only_docs,
            "contact_sales_only": contact_sales_only,
            "license_detected": license_detected,
            "update_signal": update_signal,
            "homepage_fetched_by": homepage.fetched_by,
            "anti_bot_blocked": anti_bot_blocked,
            "playwright_enabled": playwright_enabled,
            "playwright_disabled_reason": playwright_disabled_reason,
        }
