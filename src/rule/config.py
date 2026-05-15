"""
평가 파이프라인의 전역 설정값(EvalConfig)을 정의하는 모듈.

환경변수 오버라이드를 지원하는 get_rule_config() 팩토리 함수를 제공한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class EvalConfig:
    """평가 파이프라인의 수집/판정/점수화 동작을 제어하는 설정값 묶음."""

    timeout_sec: int = 12                                # 단일 HTTP 요청 타임아웃(초)
    max_candidate_pages_per_kind: int = 2                # 유형별 후보 URL 최대 수
    max_total_candidate_pages: int = 8                   # URL 1개 평가 시 후보 URL 최대 수
    max_sub_tasks: int = 5                               # taxonomy 결과에서 sub_tasks 최대 개수

    parallel_candidate_fetch: bool = True                # 후보 페이지 병렬 수집 여부
    candidate_fetch_workers: int = 4                     # 후보 페이지 병렬 수집 워커 수
    parallel_url_evaluation: bool = True                 # 입력 URL 목록 병렬 평가 여부
    url_evaluation_workers: int = 3                      # URL 병렬 평가 워커 수
    auto_tune_nested_parallel: bool = True               # URL/후보 병렬 중첩 시 후보 워커 자동 축소 여부
    skip_inter_url_delay_in_parallel: bool = True        # URL 병렬 시 inter_url_delay 적용 생략 여부

    min_curated_count: int = 4                           # count 기반 정책에서 curated 최소 통과 개수
    incubating_count: int = 3                            # count 기반 정책에서 incubating 통과 개수
    inter_url_delay_sec: float = 0.05                    # URL 간 인위적 대기(초)

    candidate_lightweight_fetch: bool = True             # 후보 페이지 수집 시 lightweight 모드 사용 여부
    max_links_per_page: int = 180                        # 페이지당 추출 링크 최대 개수
    max_body_text_chars: int = 50000                     # 페이지 본문 텍스트 최대 길이

    faq_counts_as_docs: bool = True                      # FAQ만 있어도 docs/help로 인정할지 여부
    contact_sales_counts_as_pricing: bool = False        # contact sales만 있어도 pricing으로 인정할지 여부
    terms_only_counts_as_policy: bool = True             # terms만 있어도 policy로 인정할지 여부
    license_counts_as_pricing_for_oss: bool = True       # OSS 라이선스를 pricing 근거로 인정할지 여부
    curated_requires_no_review: bool = True              # curated 확정 시 review_required=False 강제 여부
    enable_llm_for_clear_desc: bool = False              # clear_function_desc LLM 보조 판정 사용 여부
    hard_criteria: tuple[str, str] = (
        "usable_now",
        "clear_function_desc",
    )                                                    # 반드시 통과해야 하는 기준

    usable_now_weight: float = 0.30                      # usable_now 가중치
    clear_function_desc_weight: float = 0.25             # clear_function_desc 가중치
    docs_or_help_weight: float = 0.20                    # has_docs_or_help 가중치
    privacy_or_policy_weight: float = 0.20               # has_privacy_or_data_policy 가중치
    pricing_weight: float = 0.05                         # has_pricing 가중치

    curated_score_threshold: float = 85.0                # curated 점수 임계값
    incubating_score_threshold: float = 65.0             # incubating 점수 임계값
    usable_now_min_for_non_rejected: float = 0.60        # rejected 탈출 최소 usable_now 점수
    clear_desc_min_for_non_rejected: float = 0.50        # rejected 탈출 최소 clear_desc 점수
    docs_min_for_curated: float = 0.30                   # curated 최소 docs 점수
    privacy_min_for_curated: float = 0.30                # curated 최소 privacy/policy 점수
    ai_scope_uncertain_margin_low: int = -1              # ai_scope 경계구간 하한(margin)
    ai_scope_uncertain_margin_high: int = 2              # ai_scope 경계구간 상한(margin)
    ai_scope_uncertain_non_ai_score_cap: int = 6         # ai_scope 경계구간에서 허용할 non-ai 점수 상한
    taxonomy_low_confidence_threshold: float = 0.60      # taxonomy low-confidence 수동 검수 임계값
    max_change_history_per_tool: int = 50                # tool registry에서 도구별 보관할 변경 이력 최대 개수
    rule_version: str = "ai-url-classifier-rules-v1"     # 결과/이력에 기록할 규칙 버전 문자열

    use_playwright: bool = False                         # Playwright 사용 여부 (기본값 False)
    playwright_headless: bool = True                     # 브라우저 headless 실행 여부
    playwright_timeout_ms: int = 15000                   # Playwright 타임아웃(ms)
    playwright_wait_until: str = "domcontentloaded"      # page.goto wait_until 옵션
    playwright_extra_wait_ms: int = 1200                 # page.goto 이후 추가 대기(ms)
    playwright_browser: str = "chromium"                 # Playwright 브라우저 타입
    playwright_challenge_wait_ms: int = 10000            # anti-bot challenge 해소 대기(ms)
    playwright_challenge_retries: int = 1                # challenge 감지 시 재시도 횟수
    playwright_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    )                                                    # Playwright 요청 User-Agent

    min_text_len_for_static_success: int = 700           # requests 결과 최소 본문 길이 기준
    min_links_for_static_success: int = 8                # requests 결과 최소 링크 수 기준
    fallback_probe_paths: tuple[str, ...] = (
        "/pricing",
        "/plans",
        "/docs",
        "/help",
        "/support",
        "/privacy",
        "/privacy-policy",
        "/terms",
    )                                                    # 홈페이지 실패 시 추가 탐색할 기본 경로


def get_rule_config() -> EvalConfig:
    """환경변수로 EvalConfig 필드를 오버라이드하여 인스턴스를 생성한다.

    지원 환경변수:
        RULE_USE_PLAYWRIGHT: bool (기본 false)
        RULE_TIMEOUT_SEC: int (기본 12)
        RULE_PARALLEL_CANDIDATE_FETCH: bool (기본 true)
        RULE_CANDIDATE_FETCH_WORKERS: int (기본 4)
    """
    use_playwright = _parse_bool(os.getenv("RULE_USE_PLAYWRIGHT", "false"))
    timeout_sec = _parse_int(os.getenv("RULE_TIMEOUT_SEC", "12"), default=12)
    parallel_candidate_fetch = _parse_bool(os.getenv("RULE_PARALLEL_CANDIDATE_FETCH", "true"))
    candidate_fetch_workers = _parse_int(os.getenv("RULE_CANDIDATE_FETCH_WORKERS", "4"), default=4)

    return EvalConfig(
        use_playwright=use_playwright,
        timeout_sec=timeout_sec,
        parallel_candidate_fetch=parallel_candidate_fetch,
        candidate_fetch_workers=candidate_fetch_workers,
    )


def _parse_bool(value: str) -> bool:
    """문자열을 bool로 변환한다. "true"/"1"/"yes"는 True, 나머지는 False."""
    return value.strip().lower() in ("true", "1", "yes")


def _parse_int(value: str, default: int) -> int:
    """문자열을 int로 변환한다. 실패 시 default를 반환한다."""
    try:
        return int(value.strip())
    except (ValueError, AttributeError):
        return default
