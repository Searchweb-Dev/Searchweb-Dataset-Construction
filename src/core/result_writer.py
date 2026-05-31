"""분석 결과를 ai-tools.json 포맷 파일로 저장하는 유틸리티."""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.core.url import normalize_url as _normalize_url

logger = logging.getLogger(__name__)

_DATA_DIR = str(Path(__file__).parents[2] / "data")
_SOURCE_PATH = os.path.join(_DATA_DIR, "ai-tools.json")


def _favicon_url(url: str) -> str:
    """URL에서 favicon 경로를 조합한다."""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
    return ""


def _output_path(checked_at: str, source_path: str) -> str:
    """타임스탬프를 붙인 출력 파일 경로를 반환한다."""
    timestamp = checked_at.replace("-", "").replace("T", "_").replace(":", "")[:15]
    name, ext = os.path.splitext(os.path.basename(source_path))
    return os.path.join(_DATA_DIR, f"{name}_{timestamp}{ext}")


def _load_source(source_path: str) -> list[dict[str, Any]]:
    """원본 파일을 읽어 반환한다. 없으면 빈 목록."""
    if not os.path.isfile(source_path):
        return []
    try:
        with open(source_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [item for item in data if isinstance(item, dict)]
    except Exception as e:
        logger.error("원본 파일 읽기 실패: %s (%s)", source_path, e)
        return []


def _to_entry(url: str, analysis: dict[str, Any], checked_at: str) -> dict[str, Any]:
    """분석 결과 딕셔너리를 ai-tools.json 항목 형태로 변환한다."""
    categories = analysis.get("categories") or []
    primary = next((c for c in categories if c.get("is_primary")), categories[0] if categories else {})
    return {
        "name": analysis.get("title", ""),
        "desc": analysis.get("description", ""),
        "img": _favicon_url(url),
        "link": url,
        "category": primary.get("level_2") or primary.get("level_1", ""),
        "is_ai_tool": analysis.get("is_ai_tool", False),
        "tags": analysis.get("tags", []),
        "scores": analysis.get("scores", {}),
        "confidence": analysis.get("confidence", 0),
        "analyzer": analysis.get("analyzer"),
        "checked_at": checked_at,
    }


def _to_failed_entry(url: str, error: str, checked_at: str) -> dict[str, Any]:
    """실패한 분석 항목을 ai-tools.json 항목 형태로 변환한다."""
    return {
        "name": "",
        "desc": "",
        "img": _favicon_url(url),
        "link": url,
        "category": "",
        "is_ai_tool": False,
        "tags": [],
        "scores": {},
        "confidence": 0,
        "analyzer": None,
        "checked_at": checked_at,
        "error": error,
    }


def extract_unprocessed(result_path: str) -> str | None:
    """결과 파일에서 미처리 항목을 추출해 별도 JSON으로 저장한다.

    미처리 항목 기준: is_ai_tool 키가 없는 원본 그대로의 항목.
    추출 결과는 data/ 디렉토리에 <원본명>_unprocessed_<타임스탬프>.json으로 저장된다.
    DB 저장은 하지 않는다.

    Args:
        result_path: 부분 처리된 결과 파일 경로.

    Returns:
        저장된 파일 경로. 미처리 항목이 없거나 저장 실패 시 None.
    """
    items = _load_source(result_path)
    unprocessed = [item for item in items if "is_ai_tool" not in item]

    if not unprocessed:
        logger.info("미처리 항목 없음: %s", result_path)
        return None

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name, ext = os.path.splitext(os.path.basename(result_path))
    out_path = os.path.join(_DATA_DIR, f"{name}_unprocessed_{ts}{ext}")

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(unprocessed, f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info("미처리 항목 저장: %s (%d건)", out_path, len(unprocessed))
        return out_path
    except Exception as e:
        logger.error("미처리 항목 저장 실패: %s", e)
        return None


def write_batch(
    results: list[tuple[str, dict[str, Any]]],
    checked_at: str | None = None,
    failures: list[tuple[str, str]] | None = None,
    source_path: str | None = None,
) -> str | None:
    """한 배치 분석의 결과를 원본 기반 새 파일에 한 번에 저장한다.

    원본 파일을 베이스로 읽고, 이번 배치에서 분석된 항목을
    link 기준으로 추가하거나 갱신한 뒤 타임스탬프 파일로 저장한다.
    원본은 수정하지 않는다. 실패 항목은 is_ai_tool=false, error 필드와 함께 기록된다.

    Args:
        results: (url, analysis_dict) 튜플 목록. analysis는 detector 반환값.
        checked_at: 타임스탬프 문자열. 미지정 시 현재 UTC 시각.
        failures: (url, error_message) 튜플 목록. 실패한 URL과 사유.
        source_path: 베이스로 사용할 원본 파일 경로. 미지정 시 기본 ai-tools.json.

    Returns:
        저장된 파일 경로. 결과가 없거나 저장 실패 시 None.
    """
    failures = failures or []
    if not results and not failures:
        return None

    src = source_path or _SOURCE_PATH
    ts = checked_at or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = _output_path(ts, src)

    items = _load_source(src)
    link_index: dict[str, int] = {
        _normalize_url(str(item.get("link", ""))): i
        for i, item in enumerate(items)
        if item.get("link")
    }

    added = updated = 0
    for url, analysis in results:
        if not url:
            continue
        entry = _to_entry(url, analysis, ts)
        normalized = _normalize_url(url)
        if normalized in link_index:
            items[link_index[normalized]] = entry
            updated += 1
        else:
            link_index[normalized] = len(items)
            items.append(entry)
            added += 1

    failed_added = failed_updated = 0
    for url, error in failures:
        if not url:
            continue
        entry = _to_failed_entry(url, error, ts)
        normalized = _normalize_url(url)
        if normalized in link_index:
            items[link_index[normalized]] = entry
            failed_updated += 1
        else:
            link_index[normalized] = len(items)
            items.append(entry)
            failed_added += 1

    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
            f.write("\n")
        logger.info(
            "결과 파일 저장: %s (성공 추가 %d건, 갱신 %d건 / 실패 추가 %d건, 갱신 %d건)",
            out_path, added, updated, failed_added, failed_updated,
        )
        return out_path
    except Exception as e:
        logger.error("결과 파일 저장 실패: %s", e)
        return None
