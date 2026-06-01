"""src/api/job_routes.py — 작업 상태 조회 API 통합 테스트."""

import pytest
from uuid import uuid4
from sqlalchemy import text
from fastapi.testclient import TestClient


def _create_job(db, job_id, url: str, status: str, site_id=None):
    """AnalysisJob 레코드를 ORM으로 삽입한다."""
    from src.db.models.analysis_job import AnalysisJob
    job = AnalysisJob(job_id=job_id, url=url, status=status, retry_count=0)
    if site_id is not None:
        job.site_id = site_id
    db.add(job)
    db.commit()


def _create_site(db, site_id: int, url: str):
    """AISite 레코드를 직접 삽입한다."""
    db.execute(text(
        "INSERT INTO ai_site (site_id, url, is_ai_tool, status) "
        "VALUES (:sid, :url, 1, 'ok')"
    ), {"sid": site_id, "url": url})
    db.commit()


class TestGetJobStatus:
    """GET /api/v1/jobs/{job_id} 엔드포인트 검증."""

    def test_returns_404_for_unknown_job(self, client):
        job_id = uuid4()
        resp = client.get(f"/api/v1/jobs/{job_id}", headers={"x-api-key": "test-api-key-change-in-production"})
        assert resp.status_code == 404

    def test_returns_401_without_api_key(self, client, db):
        job_id = uuid4()
        _create_job(db, job_id, "https://example.com", "pending")
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 401 or resp.status_code == 422

    def test_returns_pending_job(self, client, db):
        job_id = uuid4()
        _create_job(db, job_id, "https://example.com", "pending")
        resp = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"x-api-key": "test-api-key-change-in-production"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["url"] == "https://example.com"
        assert str(data["job_id"]) == str(job_id)

    def test_returns_processing_job(self, client, db):
        job_id = uuid4()
        _create_job(db, job_id, "https://example.com", "processing")
        resp = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"x-api-key": "test-api-key-change-in-production"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"

    def test_returns_failed_job(self, client, db):
        job_id = uuid4()
        _create_job(db, job_id, "https://example.com", "failed")
        resp = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"x-api-key": "test-api-key-change-in-production"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    def test_success_job_has_null_result_without_site(self, client, db):
        job_id = uuid4()
        _create_job(db, job_id, "https://example.com", "success")
        resp = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"x-api-key": "test-api-key-change-in-production"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"] is None

    def test_invalid_uuid_returns_422(self, client):
        resp = client.get(
            "/api/v1/jobs/not-a-uuid",
            headers={"x-api-key": "test-api-key-change-in-production"},
        )
        assert resp.status_code == 422
