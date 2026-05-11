"""Celery 앱 설정."""

import os
from celery import Celery
from kombu import Exchange, Queue

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(__name__, include=["src.workers.analyze_task"])
app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60 * 5,  # 5분
    task_soft_time_limit=60 * 4,  # 4분
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# 작업 큐 설정
default_exchange = Exchange("tasks", type="topic")
app.conf.task_queues = (
    Queue("analyze", exchange=default_exchange, routing_key="analyze.#"),
)

# 작업별 라우팅
app.conf.task_routes = {
    "src.workers.analyze_task.*": {"queue": "analyze", "routing_key": "analyze.default"},
}

# 재시도 정책
app.conf.task_autoretry_for = (Exception,)
app.conf.task_max_retries = 3
app.conf.task_default_retry_delay = 60  # 1분


@app.task(bind=True)
def debug_task(self):
    """테스트용 작업."""
    print(f"Request: {self.request!r}")
