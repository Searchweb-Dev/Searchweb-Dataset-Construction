"""AI 판별 로직 테스트."""

from unittest.mock import Mock, MagicMock
import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from src.ai.detector import AIDetector
from src.db.models import AISite, AICategory, AITag


@pytest.fixture
def mock_db():
    """Mock DB 세션."""
    return Mock(spec=Session)


@pytest.fixture
def detector(mock_db):
    """AI 판별기 인스턴스."""
    return AIDetector(mock_db)


def test_detector_initialization(detector, mock_db):
    """판별기 초기화 테스트."""
    assert detector.db == mock_db
    assert detector.analyzer is not None


def test_detect_and_save_success(detector, mock_db):
    """분석 및 저장 - 성공 케이스."""
    # Mock analyze
    detector.analyzer.analyze_website = Mock(return_value={
        "is_ai_tool": True,
        "title": "Example AI",
        "description": "Test AI",
        "categories": [{"level_1": "AI", "level_2": "Chat", "level_3": "LLM", "is_primary": True}],
        "tags": ["ai", "chat"],
        "scores": {"utility": 8, "trust": 9, "originality": 7},
        "confidence": 0.95
    })
    
    # Mock DB operations
    mock_site = Mock(spec=AISite)
    mock_site.site_id = 1
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_db.add = Mock()
    mock_db.flush = Mock()
    mock_db.commit = Mock()
    
    detector._save_site = Mock(return_value=mock_site)
    
    # Execute
    result = detector.detect_and_save("https://example.com")
    
    # Verify
    assert result is not None
    assert result["is_ai_tool"] is True


def test_validate_analysis_valid():
    """분석 결과 검증 - 유효한 데이터."""
    detector = AIDetector(Mock())
    
    analysis = {
        "is_ai_tool": True,
        "title": "Test",
        "description": "Test description",
        "confidence": 0.95,
    }
    
    assert detector._validate_analysis(analysis) is True


def test_validate_analysis_missing_field():
    """분석 결과 검증 - 필드 누락."""
    detector = AIDetector(Mock())
    
    analysis = {
        "is_ai_tool": True,
        "title": "Test",
        # 'description' 누락
        "confidence": 0.95,
    }
    
    assert detector._validate_analysis(analysis) is False


def test_validate_analysis_invalid_confidence():
    """분석 결과 검증 - 신뢰도 범위 오류."""
    detector = AIDetector(Mock())
    
    analysis = {
        "is_ai_tool": True,
        "title": "Test",
        "description": "Test",
        "confidence": 1.5,  # 범위 초과
    }
    
    assert detector._validate_analysis(analysis) is False
