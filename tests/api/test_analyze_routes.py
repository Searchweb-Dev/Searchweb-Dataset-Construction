"""src/api/api/v1/analyze_routes.py — 분석 요청 API 통합 테스트."""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


API_KEY = "test-api-key-change-in-production"
HEADERS = {"x-api-key": API_KEY}


class TestAnalyzeEndpoint:
    """POST /api/v1/analyze 엔드포인트 검증."""

    def test_returns_401_without_key(self, client):
        resp = client.post("/api/v1/analyze", json={"urls": ["https://example.com"]})
        assert resp.status_code == 401 or resp.status_code == 422

    def test_accepts_single_url(self, client):
        with patch("src.api.analyze_routes.analyze_urls_batch") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/api/v1/analyze",
                json={"urls": ["https://example.com"]},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["url"] == "https://example.com"
        assert data[0]["status"] == "pending"

    def test_accepts_multiple_urls(self, client):
        with patch("src.api.analyze_routes.analyze_urls_batch") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/api/v1/analyze",
                json={"urls": ["https://a.com", "https://b.com"]},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        assert len(resp.json()) == 2

    def test_rejects_more_than_5_urls(self, client):
        urls = [f"https://site{i}.com" for i in range(6)]
        resp = client.post("/api/v1/analyze", json={"urls": urls}, headers=HEADERS)
        assert resp.status_code == 422

    def test_rejects_empty_urls(self, client):
        resp = client.post("/api/v1/analyze", json={"urls": []}, headers=HEADERS)
        assert resp.status_code == 422

    def test_dispatches_celery_task(self, client):
        with patch("src.api.analyze_routes.analyze_urls_batch") as mock_task:
            mock_task.delay = MagicMock()
            client.post(
                "/api/v1/analyze",
                json={"urls": ["https://example.com"]},
                headers=HEADERS,
            )
        mock_task.delay.assert_called_once()

    def test_cache_hit_returns_existing_job(self, client, db):
        from sqlalchemy import text
        from uuid import uuid4
        # LLM 분석된 사이트 레코드 직접 삽입
        site_id = 100
        url = "https://cached.com"
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, analyzer) "
            "VALUES (:sid, :url, 1, 'ok', 'gemini')"
        ), {"sid": site_id, "url": url})
        job_id = uuid4()
        db.execute(text(
            "INSERT INTO analysis_job (job_id, url, status, site_id, retry_count) "
            "VALUES (:jid, :url, 'success', :sid, 0)"
        ), {"jid": str(job_id), "url": url, "sid": site_id})
        db.commit()

        with patch("src.api.analyze_routes.analyze_urls_batch") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/api/v1/analyze",
                json={"urls": [url]},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data[0]["status"] == "success"
        mock_task.delay.assert_not_called()

    def test_force_reanalyze_bypasses_cache(self, client, db):
        from sqlalchemy import text
        from uuid import uuid4
        site_id = 101
        url = "https://cached2.com"
        db.execute(text(
            "INSERT INTO ai_site (site_id, url, is_ai_tool, status, analyzer) "
            "VALUES (:sid, :url, 1, 'ok', 'gemini')"
        ), {"sid": site_id, "url": url})
        db.commit()

        with patch("src.api.analyze_routes.analyze_urls_batch") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/api/v1/analyze",
                json={"urls": [url], "force_reanalyze": True},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        mock_task.delay.assert_called_once()


class TestAnalyzeBatchUpload:
    """POST /api/v1/analyze/batch/upload 엔드포인트 검증."""

    def test_uploads_text_file(self, client):
        with patch("src.api.analyze_routes.analyze_urls_bulk") as mock_task:
            mock_task.delay = MagicMock()
            content = b"https://a.com\nhttps://b.com\nhttps://c.com"
            resp = client.post(
                "/api/v1/analyze/batch/upload",
                files={"file": ("urls.txt", content, "text/plain")},
                data={"force_reanalyze": "false"},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        data = resp.json()
        assert data["total"] == 3
        assert data["accepted"] == 3
        mock_task.delay.assert_called_once()

    def test_uploads_json_file(self, client):
        with patch("src.api.analyze_routes.analyze_urls_bulk") as mock_task:
            mock_task.delay = MagicMock()
            content = json.dumps(["https://a.com", "https://b.com"]).encode()
            resp = client.post(
                "/api/v1/analyze/batch/upload",
                files={"file": ("urls.json", content, "application/json")},
                data={"force_reanalyze": "false"},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        assert resp.json()["total"] == 2

    def test_returns_400_for_empty_file(self, client):
        with patch("src.api.analyze_routes.analyze_urls_bulk") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/api/v1/analyze/batch/upload",
                files={"file": ("empty.txt", b"", "text/plain")},
                data={"force_reanalyze": "false"},
                headers=HEADERS,
            )
        assert resp.status_code == 400

    def test_returns_401_without_key(self, client):
        content = b"https://a.com"
        resp = client.post(
            "/api/v1/analyze/batch/upload",
            files={"file": ("urls.txt", content, "text/plain")},
            data={"force_reanalyze": "false"},
        )
        assert resp.status_code == 401 or resp.status_code == 422


class TestAnalyzeBatchFile:
    """POST /api/v1/analyze/batch/file 엔드포인트 검증."""

    def test_returns_400_for_path_traversal(self, client):
        resp = client.post(
            "/api/v1/analyze/batch/file",
            json={"file_path": "/etc/passwd"},
            headers=HEADERS,
        )
        assert resp.status_code == 400

    def test_returns_404_for_nonexistent_file(self, client, tmp_path, monkeypatch):
        import src.core.batch_file as bf
        monkeypatch.setattr(bf, "_ALLOWED_BASE", str(tmp_path))
        resp = client.post(
            "/api/v1/analyze/batch/file",
            json={"file_path": str(tmp_path / "no_file.txt")},
            headers=HEADERS,
        )
        assert resp.status_code == 404

    def test_dispatches_task_for_valid_file(self, client, tmp_path, monkeypatch):
        import src.core.batch_file as bf
        monkeypatch.setattr(bf, "_ALLOWED_BASE", str(tmp_path))
        f = tmp_path / "urls.txt"
        f.write_text("https://a.com\nhttps://b.com")

        with patch("src.api.analyze_routes.analyze_urls_bulk") as mock_task:
            mock_task.delay = MagicMock()
            resp = client.post(
                "/api/v1/analyze/batch/file",
                json={"file_path": str(f)},
                headers=HEADERS,
            )
        assert resp.status_code == 202
        assert resp.json()["total"] == 2
        mock_task.delay.assert_called_once()
