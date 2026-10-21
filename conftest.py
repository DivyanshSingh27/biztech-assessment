import pytest
import redis
from celery.contrib.testing.worker import start_worker
from django.conf import settings

import mailer.tasks  # noqa: F401  (make sure the task is registered)
from config.celery import app


@pytest.fixture
def redis_client():
    client = redis.Redis.from_url(settings.REDIS_URL)
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture
def celery_worker_running(redis_client, transactional_db):
    """Run a real Celery worker in a background thread against test Redis."""
    with start_worker(app, perform_ping_check=False, pool="solo", loglevel="WARNING") as worker:
        yield worker
