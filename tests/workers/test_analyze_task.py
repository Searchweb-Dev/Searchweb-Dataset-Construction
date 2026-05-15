"""Celery 분석 작업 테스트."""

from uuid import uuid4
import pytest


def test_analyze_url_task_exists():
    """분석 작업 존재 확인."""
    from src.workers.analyze_task import analyze_url

    assert analyze_url is not None
    assert hasattr(analyze_url, "name")


def test_celery_app_configured():
    """Celery 앱 설정 확인."""
    from src.workers.celery_app import app
    
    assert app is not None
    assert app.conf.broker_url is not None
    assert app.conf.result_backend is not None
