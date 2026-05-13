"""LLM 분석용 프롬프트 상수.

응답 스키마:
{
  "is_ai_tool": bool,
  "title": str,
  "description": str,          # 한글 50자 이내
  "categories": [{
    "level_1": str,             # 대분류: text|image|video|audio|code|multimodal|data|business
    "level_2": str,             # 중분류: text-generation|image-generation|code-generation 등
    "level_3": str | None,      # 소분류 (추후 사용)
    "is_primary": bool
  }],                           # 1개
  "tags": [str],                # 최대 3개
  "scores": {"utility": int, "trust": int, "originality": int},  # 1-10
  "confidence": float           # 0-1
}
"""

SYSTEM_PROMPT = """당신은 웹사이트 분석 전문가입니다.
주어진 URL의 페이지를 분석하여 판정하세요:

1. AI 도구/서비스 여부 (ChatGPT, Claude, 이미지생성AI 등 AI 기술 기반 서비스)
2. 서비스 분류 (대/중분류)
3. 주요 기능 태그 (최대 3개)
4. 유용성·신뢰도·독창성 점수 (1-10)

신중하고 객관적으로 판정하세요."""

# 단건 분석 프롬프트 — response_schema로 형식을 강제하므로 예시 JSON 불필요
ANALYSIS_PROMPT = "다음 URL의 웹사이트를 분석하세요.\n\nURL: {url}"

# 배치 분석 프롬프트 — URL N개를 한 번에 분석, 순서 보장 필수
BATCH_ANALYSIS_PROMPT = """다음 URL 목록의 웹사이트를 각각 분석하세요. 입력 순서와 동일한 순서로 결과를 반환하세요.

{url_list}"""
