"""
URL/텍스트 처리와 규칙 판정에 공통으로 쓰는 유틸 함수 모듈.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from src.rule.keywords import (
    DOCS_TEXT,
    EXTERNAL_DOCS_HOST_PREFIXES,
    EXTERNAL_POLICY_HOSTS,
    POLICY_TEXT,
    PRICE_VALUE_RE,
    STRONG_PRICING_TEXT,
)


def normalize_url(url: str) -> str:
    """입력 URL을 스킴/호스트/경로 기준의 정규화 형태로 변환한다."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    p = urlparse(url.strip())
    scheme = p.scheme or "https"
    netloc = p.netloc.lower()
    path = p.path or "/"
    return urlunparse((scheme, netloc, path.rstrip("/") or "/", "", "", ""))


def get_domain(url: str) -> str:
    """URL에서 소문자 도메인(host) 문자열만 추출한다."""
    return urlparse(url).netloc.lower()


def is_same_domain(url1: str, url2: str) -> bool:
    """두 URL이 같은 도메인인지 비교한다."""
    return get_domain(url1) == get_domain(url2)


def squash_ws(text: str) -> str:
    """연속 공백/개행을 단일 공백으로 정리한다."""
    return re.sub(r"\s+", " ", text or "").strip()


def lower(text: str) -> str:
    """공백 정규화 후 소문자로 변환한다."""
    return squash_ws(text).lower()


def snippet(text: str, max_len: int = 220) -> str:
    """텍스트를 지정 길이 내의 요약 스니펫으로 자른다."""
    text = squash_ws(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def keyword_hit(text: str, keywords: set[str]) -> bool:
    """텍스트에 키워드 집합 중 하나라도 포함되는지 검사한다."""
    t = lower(text)
    return any(k in t for k in keywords)


def keyword_hit_count(text: str, keywords: set[str], normalized: bool = False) -> int:
    """텍스트에 포함된 키워드 개수를 센다."""
    t = text if normalized else lower(text)
    return sum(1 for k in keywords if k in t)


def split_sentences(text: str) -> list[str]:
    """문단 텍스트를 문장 단위 리스트로 분리한다."""
    text = squash_ws(text)
    raw = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [s.strip() for s in raw if len(s.strip()) >= 20]


def has_pricing_url_hint(url: str) -> bool:
    """URL 경로가 pricing/plans 계열 힌트를 가지는지 확인한다."""
    path = lower(urlparse(url).path or "/")
    segments = [seg for seg in path.strip("/").split("/") if seg]
    pricing_segments = {"pricing", "plans", "plan", "billing", "subscription", "price"}
    return any(seg in pricing_segments for seg in segments)


def has_usable_url_hint(url: str) -> bool:
    """URL 경로가 즉시 사용 진입(signup/app/create 등) 힌트를 가지는지 확인한다."""
    path = lower(urlparse(url).path or "/")
    segments = [seg for seg in path.strip("/").split("/") if seg]
    usable_segments = {
        "signup",
        "sign-up",
        "register",
        "login",
        "app",
        "create",
        "studio",
        "editor",
        "dashboard",
        "workspace",
        "generate",
        "playground",
    }
    return any(seg in usable_segments for seg in segments)


def is_likely_pricing_link(link_text: str, href: str) -> bool:
    """링크 텍스트/URL로 pricing 관련 링크 가능성을 판정한다."""
    blob = lower(f"{link_text} {href}")
    return has_pricing_url_hint(href) or keyword_hit(blob, STRONG_PRICING_TEXT)


def is_strong_pricing_page(url: str, title: str, meta_description: str, text: str) -> bool:
    """페이지가 공개 가격/플랜 정보를 담은 강한 pricing 페이지인지 판정한다."""
    content_blob = lower(" ".join([meta_description, text[:4000]]))
    has_pricing_path = has_pricing_url_hint(url)
    has_price_value = bool(PRICE_VALUE_RE.search(content_blob))
    has_plan_term = any(
        k in content_blob
        for k in [
            "pricing",
            "plans",
            "billing",
            "subscription",
            "monthly",
            "annual",
            "per seat",
            "per user",
            "요금",
            "가격",
            "플랜",
            "구독",
            "월",
            "연",
        ]
    )
    has_placeholder_signal = any(k in content_blob for k in ["coming soon", "under construction", "출시 예정", "준비 중"])

    if has_price_value:
        return True
    if has_pricing_path and has_plan_term and not has_placeholder_signal:
        return True
    return False


def is_allowed_external_docs_link(link_text: str, href: str) -> bool:
    """외부 도메인 링크를 docs/help 근거로 허용할 수 있는지 판정한다."""
    if not keyword_hit(f"{link_text} {href}", DOCS_TEXT):
        return False
    host = get_domain(href)
    if any(host.startswith(prefix) for prefix in EXTERNAL_DOCS_HOST_PREFIXES):
        return True
    return any(p in lower(href) for p in ["/help", "/docs", "/support", "/faq"])


def is_allowed_external_policy_link(link_text: str, href: str) -> bool:
    """외부 도메인 링크를 policy 근거로 허용할 수 있는지 판정한다."""
    blob = lower(f"{link_text} {href}")
    if not keyword_hit(blob, POLICY_TEXT):
        return False
    host = get_domain(href)
    if any(host == h or host.endswith("." + h) for h in EXTERNAL_POLICY_HOSTS):
        return True
    return any(p in lower(href) for p in ["/privacy", "/policy", "/terms", "/security"])


def likely_related_external_candidates(homepage_url: str) -> list[str]:
    """도메인 규칙 기반으로 추가 탐색할 외부 후보 URL 목록을 생성한다."""
    host = get_domain(homepage_url)
    candidates: list[str] = []
    if host.endswith("chatgpt.com") or host.endswith("openai.com"):
        candidates.extend([
            "https://chatgpt.com/pricing",
            "https://help.openai.com/en/",
            "https://openai.com/policies/row-privacy-policy/",
        ])
    dedup: list[str] = []
    seen = set()
    for u in candidates:
        nu = normalize_url(u)
        if nu in seen:
            continue
        seen.add(nu)
        dedup.append(nu)
    return dedup
