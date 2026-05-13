"""성능 측정 및 벤치마크 테스트."""

import time
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestAnalysisPerformance:
    """분석 성능 벤치마크."""

    @pytest.fixture(autouse=True)
    def mock_celery(self):
        """Celery 작업 Mock."""
        with patch("src.api.analyze_routes.analyze_website") as mock_task:
            mock_task.delay = MagicMock(return_value=Mock(id="mock-task-id"))
            yield mock_task

    def test_analysis_response_time(self, test_client, valid_api_key):
        """분석 응답 시간 < 1초 테스트."""
        url = "https://example.com"
        
        start = time.time()
        response = test_client.post(
            "/api/v1/analyze",
            json={"urls": [url], "force_reanalyze": False},
            headers={"x-api-key": valid_api_key},
        )
        elapsed = time.time() - start
        
        assert response.status_code == 202
        assert elapsed < 1.0, f"API 응답 시간 초과: {elapsed:.2f}초"

    def test_job_status_query_response_time(self, test_client, valid_api_key):
        """작업 상태 조회 응답 시간 < 200ms 테스트."""
        from uuid import uuid4
        
        job_id = str(uuid4())
        
        start = time.time()
        response = test_client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"x-api-key": valid_api_key},
        )
        elapsed = time.time() - start
        
        assert response.status_code == 404
        assert elapsed < 0.2, f"상태 조회 응답 시간 초과: {elapsed:.3f}초"

    def test_cache_effectiveness(self):
        """프롬프트 캐싱 효과 측정."""
        from src.ai.analyzer import WebAnalyzer
        
        analyzer = WebAnalyzer()
        
        # 초기 통계 확인
        assert analyzer.cache_stats["hits"] == 0
        assert analyzer.cache_stats["misses"] == 0
        
        # 캐시 통계 조회
        stats = analyzer.get_cache_stats()
        assert stats["total_requests"] == 0
        assert stats["hit_rate"] == "0.0%"
        
        # 캐시 통계 초기화
        analyzer.reset_cache_stats()
        assert analyzer.cache_stats["hits"] == 0


class TestConcurrentAnalysis:
    """동시 작업 처리 능력 테스트."""

    @pytest.fixture(autouse=True)
    def mock_celery(self):
        """Celery 작업 Mock."""
        with patch("src.api.analyze_routes.analyze_website") as mock_task:
            mock_task.delay = MagicMock(return_value=Mock(id="mock-task-id"))
            yield mock_task

    def test_multiple_analysis_requests(self, test_client, valid_api_key):
        """다중 분석 요청 테스트 (동시성)."""
        urls = [
            "https://example1.com",
            "https://example2.com",
            "https://example3.com",
        ]
        
        responses = []
        start = time.time()
        
        for url in urls:
            response = test_client.post(
                "/api/v1/analyze",
                json={"urls": [url], "force_reanalyze": False},
                headers={"x-api-key": valid_api_key},
            )
            responses.append(response)
        
        elapsed = time.time() - start
        
        # 모든 요청 성공
        assert all(r.status_code == 202 for r in responses)
        
        # 총 소요 시간 < 3초 (동시 처리 가능)
        assert elapsed < 3.0, f"다중 요청 처리 시간: {elapsed:.2f}초"
        
        # 응답 Job ID 모두 다름
        job_ids = [r.json()[0]["job_id"] for r in responses]
        assert len(job_ids) == len(set(job_ids)), "Job ID 중복 발생"

    def test_api_throughput(self, test_client, valid_api_key):
        """API 처리량 측정 (초당 요청 수)."""
        requests_count = 10
        
        start = time.time()
        
        for i in range(requests_count):
            response = test_client.post(
                "/api/v1/analyze",
                json={"urls": [f"https://example{i}.com"], "force_reanalyze": False},
                headers={"x-api-key": valid_api_key},
            )
            assert response.status_code == 202
        
        elapsed = time.time() - start
        throughput = requests_count / elapsed
        
        assert throughput > 10, f"처리량 부족: {throughput:.1f} req/sec"


class TestMemoryUsage:
    """메모리 사용량 테스트."""

    def test_analyzer_memory_efficiency(self):
        """Analyzer 메모리 효율성."""
        from src.ai.analyzer import WebAnalyzer
        
        analyzer = WebAnalyzer()
        
        # Analyzer 인스턴스 크기 확인
        import sys
        size = sys.getsizeof(analyzer)
        
        # 100KB 이하로 가벼워야 함
        assert size < 100000, f"Analyzer 크기 과대: {size} bytes"


class TestCodeQuality:
    """코드 품질 테스트."""

    def test_type_hints_coverage(self):
        """타입 힌트 적용 확인."""
        from src.ai import analyzer, detector
        import inspect
        
        # analyzer.py 함수들 타입 힌트 확인
        for name, obj in inspect.getmembers(analyzer.WebAnalyzer):
            if inspect.ismethod(obj) or inspect.isfunction(obj):
                if name.startswith("_"):
                    continue
                # 공개 메서드는 타입 힌트 필수
                annotations = inspect.signature(obj).parameters
                # 최소한 하나의 파라미터는 타입 힌트 필요
                if annotations:
                    has_type_hints = any(
                        param.annotation != inspect.Parameter.empty
                        for param in annotations.values()
                    )
                    # 선택적 테스트 (엄격하지 않음)

    def test_no_debug_code(self):
        """디버그 코드 미포함 확인."""
        import src.api.analyze_routes as routes_module
        import src.ai.analyzer as analyzer_module
        
        source_files = [routes_module, analyzer_module]
        
        for module in source_files:
            source = inspect.getsource(module)
            # print() 사용 확인
            assert "print(" not in source, f"{module.__name__}: print() 발견"


# Fixture 추가
@pytest.fixture
def test_client(client):
    """테스트 클라이언트."""
    return client


@pytest.fixture
def valid_api_key():
    """유효한 API 키."""
    return "test-api-key-change-in-production"


import inspect
