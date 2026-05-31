"""Gemini API를 사용한 웹사이트 분석기 (url_context + Structured Output 방식)."""

import logging
import time
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from src.ai.config import (
    get_gemini_model,
    get_gemini_retry_multiplier,
    get_gemini_retry_min_wait,
    get_gemini_retry_max_wait,
    get_gemini_retry_attempts,
)
from src.ai.response_parser import (
    parse_single,
    parse_batch,
    check_finish_reason,
    compute_quality_fields,
)
from src.core.error_policy import (
    ApiErrorKind,
    classify_api_error,
    get_policy,
    RateLimitError,
    ApiServerUnavailableError,
    ApiServerInternalError,
    ApiUnauthenticatedError,
    ApiPermissionDeniedError,
    ApiTimeoutError,
    ApiPreconditionError,
    ApiNotFoundError,
)
from src.core.exceptions import SiteUnreachableError
from src.ai.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT, BATCH_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)

# Structured Output 응답 스키마
_SITE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_ai_tool": {"type": "boolean"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "level_1": {"type": "string"},
                    "level_2": {"type": "string"},
                    "level_3": {"type": "string"},
                    "is_primary": {"type": "boolean"},
                },
                "required": ["level_1", "level_2", "is_primary"],
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "scores": {
            "type": "object",
            "properties": {
                "utility": {"type": "integer"},
                "trust": {"type": "integer"},
                "originality": {"type": "integer"},
            },
            "required": ["utility", "trust", "originality"],
        },
        "confidence": {"type": "number"},
    },
    "required": ["is_ai_tool", "title", "description", "categories", "tags", "scores", "confidence"],
}

_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": _SITE_SCHEMA,
        }
    },
    "required": ["results"],
}

_KIND_TO_EXC_CLS: dict[ApiErrorKind, tuple[type, str]] = {
    ApiErrorKind.UNREACHABLE:         (SiteUnreachableError,       "사이트 접근 불가 (400)"),
    ApiErrorKind.PRECONDITION_FAILED: (ApiPreconditionError,       "사전 조건 미충족 (400)"),
    ApiErrorKind.NOT_FOUND:           (ApiNotFoundError,           "리소스 없음 (404)"),
    ApiErrorKind.AUTH_ERROR:          (ApiUnauthenticatedError,    "API 인증 실패 (401)"),
    ApiErrorKind.PERMISSION_DENIED:   (ApiPermissionDeniedError,   "API 권한 없음 (403)"),
    ApiErrorKind.RATE_LIMITED:        (RateLimitError,             "API 할당량 초과 (429)"),
    ApiErrorKind.TIMEOUT:             (ApiTimeoutError,            "API 타임아웃 (504)"),
    ApiErrorKind.SERVER_UNAVAILABLE:  (ApiServerUnavailableError,  "API 서버 일시 불가 (503)"),
    ApiErrorKind.SERVER_INTERNAL:     (ApiServerInternalError,     "API 서버 내부 오류 (500)"),
}


def _is_retryable(exc: BaseException) -> bool:
    """재시도 가능한 오류인지 판별한다."""
    return get_policy(exc).retryable


def _raise_typed_error(exc: BaseException, url: str) -> None:
    """에러 종류에 따라 적절한 도메인 예외를 발생시킨다."""
    kind = classify_api_error(exc)
    if kind in _KIND_TO_EXC_CLS:
        exc_cls, msg = _KIND_TO_EXC_CLS[kind]
        raise exc_cls(f"{msg}: {url}") from exc
    raise exc


class GeminiAnalyzer:
    """Gemini url_context 툴 + Structured Output을 사용한 웹사이트 분석기."""

    def __init__(self, api_key: str | None = None):
        """Gemini 클라이언트 초기화."""
        self.client = genai.Client(api_key=api_key)
        self.model = get_gemini_model()

    def analyze_website(self, url: str) -> dict[str, Any]:
        """단건 URL 분석."""
        logger.info("[Gemini] 단건 분석 시작: %s", url)
        start_time = time.time()
        try:
            response = self._generate(ANALYSIS_PROMPT.format(url=url), _SITE_SCHEMA)
        except Exception as exc:
            _raise_typed_error(exc, url)
        check_finish_reason(url, response)

        result = parse_single(response)
        result["analyzer"] = "gemini"
        result.update(compute_quality_fields(result))

        elapsed = time.time() - start_time
        logger.info(
            "[Gemini] 단건 분석 완료: %s | is_ai_tool=%s confidence=%.2f (%.2f초)",
            url, result.get("is_ai_tool"), result.get("confidence", 0), elapsed,
        )
        return result

    def analyze_websites_batch(self, urls: list[str]) -> list[dict[str, Any]]:
        """URL 목록을 LLM 호출 1회로 배치 분석한다.

        Args:
            urls: 분석할 URL 목록 (1~5개).

        Returns:
            입력 순서와 동일한 순서의 분석 결과 리스트.
            개별 URL 파싱 실패 시 해당 항목을 기본값으로 채운다.
        """
        if not urls:
            return []
        if len(urls) == 1:
            return [self.analyze_website(urls[0])]

        logger.info("[Gemini] 배치 분석 시작: %d개 URL %s", len(urls), urls)
        start_time = time.time()
        url_list = "\n".join(f"{i}. {url}" for i, url in enumerate(urls, start=1))
        prompt = BATCH_ANALYSIS_PROMPT.format(url_list=url_list)

        response = self._generate(prompt, _BATCH_SCHEMA)
        check_finish_reason(",".join(urls), response)

        results = parse_batch(response, urls)
        for r in results:
            r.update(compute_quality_fields(r))

        elapsed = time.time() - start_time
        logger.info("[Gemini] 배치 분석 완료: %d개 URL (%.2f초)", len(urls), elapsed)
        for url, result in zip(urls, results):
            logger.info(
                "[Gemini]   └ %s | is_ai_tool=%s confidence=%.2f title=%r",
                url, result.get("is_ai_tool"), result.get("confidence", 0), result.get("title", ""),
            )
        return results

    @retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(
            multiplier=get_gemini_retry_multiplier(),
            min=get_gemini_retry_min_wait(),
            max=get_gemini_retry_max_wait(),
        ),
        stop=stop_after_attempt(get_gemini_retry_attempts()),
        reraise=True,
    )
    def _generate(self, contents: str, schema: dict) -> Any:
        """503/429 시 지수 백오프 재시도."""
        return self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(url_context=types.UrlContext())],
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
