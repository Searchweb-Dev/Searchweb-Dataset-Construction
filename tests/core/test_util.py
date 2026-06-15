"""src/core/util.py — utc_now 단위 테스트."""

from datetime import datetime
from src.core.util import utc_now


class TestUtcNow:
    """utc_now 반환값 검증."""

    def test_returns_datetime(self):
        result = utc_now()
        assert isinstance(result, datetime)

    def test_returns_naive_datetime(self):
        # DB DateTime(timezone=False)에 호환되려면 tzinfo가 없어야 함
        result = utc_now()
        assert result.tzinfo is None

    def test_returns_recent_time(self):
        # 현재 UTC와 1초 이내 차이여야 함
        from datetime import timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        result = utc_now()
        diff = abs((result - now).total_seconds())
        assert diff < 1.0

    def test_monotonically_increasing(self):
        t1 = utc_now()
        t2 = utc_now()
        assert t2 >= t1
