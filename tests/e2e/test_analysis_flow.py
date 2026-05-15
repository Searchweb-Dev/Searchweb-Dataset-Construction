"""E2E 통합 테스트: 분석 요청부터 결과 조회까지."""

from unittest.mock import Mock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client(client):
    """테스트 클라이언트."""
    return client


@pytest.fixture
def valid_api_key():
    """유효한 API 키."""
    return "test-api-key-change-in-production"


@pytest.fixture(autouse=True)
def mock_celery_task():
    """Celery 작업 Mock."""
    with patch("src.api.analyze_routes.analyze_urls_batch") as mock_task:
        mock_task.delay = MagicMock(return_value=Mock(id="mock-task-id"))
        yield mock_task


class TestAnalysisAPI:
    """분석 API 통합 테스트."""

    def test_analyze_request_invalid_api_key(self, test_client):
        """분석 요청 - 잘못된 API 키."""
        response = test_client.post(
            "/api/v1/analyze",
            json={"urls": ["https://example.com"], "force_reanalyze": False},
            headers={"x-api-key": "wrong-key"},
        )

        assert response.status_code == 403
        assert "Invalid API Key" in response.json()["detail"]

    def test_analyze_request_missing_api_key(self, test_client):
        """분석 요청 - API 키 누락."""
        response = test_client.post(
            "/api/v1/analyze",
            json={"urls": ["https://example.com"], "force_reanalyze": False},
        )

        assert response.status_code == 422

    def test_analyze_request_invalid_url(self, test_client, valid_api_key):
        """분석 요청 - 잘못된 URL 형식."""
        response = test_client.post(
            "/api/v1/analyze",
            json={"urls": ["not-a-url"], "force_reanalyze": False},
            headers={"x-api-key": valid_api_key},
        )

        assert response.status_code == 422

    def test_analyze_request_success(self, test_client, valid_api_key):
        """분석 요청 - 성공."""
        response = test_client.post(
            "/api/v1/analyze",
            json={"urls": ["https://example.com"], "force_reanalyze": False},
            headers={"x-api-key": valid_api_key},
        )

        assert response.status_code == 202
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["status"] == "pending"
        assert "job_id" in data[0]
        assert data[0]["url"].startswith("https://example.com")
        assert data[0]["retry_count"] == 0
        assert data[0]["error_message"] is None

    def test_job_status_invalid_api_key(self, test_client):
        """작업 상태 조회 - 잘못된 API 키."""
        response = test_client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000",
            headers={"x-api-key": "wrong-key"},
        )

        assert response.status_code == 403

    def test_job_status_missing_api_key(self, test_client):
        """작업 상태 조회 - API 키 누락."""
        response = test_client.get(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000",
        )

        assert response.status_code == 422

    def test_job_status_not_found(self, test_client, valid_api_key):
        """작업 상태 조회 - Job 미존재."""
        from uuid import uuid4

        job_id = str(uuid4())
        response = test_client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"x-api-key": valid_api_key},
        )

        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]

    def test_analyze_with_force_reanalyze(self, test_client, valid_api_key):
        """분석 요청 - 강제 재분석."""
        response = test_client.post(
            "/api/v1/analyze",
            json={"urls": ["https://example.com"], "force_reanalyze": True},
            headers={"x-api-key": valid_api_key},
        )

        assert response.status_code == 202
        data = response.json()
        assert isinstance(data, list)
        assert data[0]["status"] == "pending"


class TestHealthCheck:
    """헬스 체크 테스트."""

    def test_health_check(self, test_client):
        """헬스 체크 엔드포인트."""
        response = test_client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
