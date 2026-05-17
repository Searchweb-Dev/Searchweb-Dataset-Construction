"""Celery 앱 설정."""

import logging
import os
from typing import Any

from celery import Celery
from celery.signals import setup_logging
from dotenv import load_dotenv
from kombu import Exchange, Queue

load_dotenv()

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

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
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_loglevel=log_level,
)


@setup_logging.connect
def configure_logging(**kwargs: Any) -> None:
    """Celery worker 로그 레벨을 환경변수 LOG_LEVEL로 통일한다."""
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
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
