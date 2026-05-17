"""배치 분석용 파일에서 URL을 추출하는 유틸리티."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_URLS = 500
_ALLOWED_BASE = str(Path(__file__).parents[2] / "data")


def extract_urls_from_bytes(content: bytes, filename: str = "") -> list[str]:
    """파일 바이트에서 URL 목록을 추출한다.

    JSON 파일: 문자열 배열 또는 {"link": ...} 객체 배열을 지원한다.
    텍스트 파일: 한 줄에 URL 하나.

    Args:
        content: 파일 내용 바이트.
        filename: 원본 파일명 (확장자로 형식 판별).

    Returns:
        추출된 URL 문자열 목록 (최대 500개).

    Raises:
        ValueError: URL을 하나도 추출할 수 없는 경우.
    """
    is_json = filename.endswith(".json") if filename else _looks_like_json(content)

    if is_json:
        urls = _parse_json(content)
    else:
        urls = _parse_text(content)

    if not urls:
        raise ValueError("파일에서 유효한 URL을 찾을 수 없습니다.")

    if len(urls) > _MAX_URLS:
        logger.warning("URL이 %d개로 상한(%d)을 초과해 잘라냅니다.", len(urls), _MAX_URLS)
        urls = urls[:_MAX_URLS]

    return urls


def extract_urls_from_path(file_path: str) -> list[str]:
    """서버 경로 파일에서 URL 목록을 추출한다.

    data/ 디렉터리 하위 파일만 허용한다.

    Args:
        file_path: 서버 내 파일 경로.

    Returns:
        추출된 URL 문자열 목록 (최대 500개).

    Raises:
        ValueError: 허용되지 않는 경로인 경우.
        FileNotFoundError: 파일이 존재하지 않는 경우.
        ValueError: URL을 하나도 추출할 수 없는 경우.
    """
    real = os.path.realpath(file_path)
    if not real.startswith(_ALLOWED_BASE + os.sep):
        raise ValueError(f"허용되지 않는 경로입니다: {file_path}")

    if not os.path.isfile(real):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    with open(real, "rb") as f:
        content = f.read()

    return extract_urls_from_bytes(content, filename=file_path)


def _looks_like_json(content: bytes) -> bool:
    """내용 앞부분으로 JSON 여부를 추정한다."""
    stripped = content.lstrip()
    return stripped.startswith(b"[") or stripped.startswith(b"{")


def _parse_json(content: bytes) -> list[str]:
    """JSON 파일에서 URL을 추출한다."""
    try:
        data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"JSON 파싱 실패: {e}") from e

    if isinstance(data, list):
        urls = []
        for item in data:
            if isinstance(item, str):
                urls.append(item.strip())
            elif isinstance(item, dict):
                # {"link": "..."} 또는 {"url": "..."} 형태 지원
                url = item.get("link") or item.get("url")
                if url and isinstance(url, str):
                    urls.append(url.strip())
        return [u for u in urls if u]

    raise ValueError("JSON은 배열 형식이어야 합니다.")


def _parse_text(content: bytes) -> list[str]:
    """텍스트 파일에서 URL을 추출한다. 한 줄에 URL 하나."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("UTF-8 디코딩 실패, 오류 문자를 대체 문자로 처리합니다.")
        text = content.decode("utf-8", errors="replace")

    return [line.strip() for line in text.splitlines() if line.strip()]
