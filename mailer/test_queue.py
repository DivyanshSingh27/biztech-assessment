import collections
import time

from django.conf import settings

from mailer.models import EmailJob
from mailer.provider import ProviderError
from mailer.services import enqueue_email

TOTAL_JOBS = 500
FAIL_ONCE_KEY = "job-0042"
TOLERANCE_MS = 150  # the fake provider records a few ms after the limiter allows
SENT_LOG = "test:sent"


def wait_for(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return False


def test_500_jobs_no_loss_rate_limit_respected_and_failure_retried(
    celery_worker_running, redis_client, monkeypatch
):
    calls = collections.Counter()

    def fake_provider(job):
        key = job.idempotency_key
        calls[key] += 1
        if key == FAIL_ONCE_KEY and calls[key] == 1:
            raise ProviderError("simulated provider outage")
        sec, micro = redis_client.time()
        redis_client.rpush(SENT_LOG, f"{key}:{sec * 1000 + micro // 1000}")

    monkeypatch.setattr("mailer.tasks.send_via_provider", fake_provider)

    keys = [f"job-{i:04d}" for i in range(TOTAL_JOBS)]
    for key in keys:
        enqueue_email(key, f"{key}@example.com", "Order confirmed", "Thanks")

    finished = wait_for(
        lambda: EmailJob.objects.filter(status=EmailJob.Status.SENT).count() == TOTAL_JOBS,
        timeout=120,
    )
    sent_count = EmailJob.objects.filter(status=EmailJob.Status.SENT).count()
    assert finished, f"only {sent_count} of {TOTAL_JOBS} jobs reached SENT"

    records = [e.decode().rsplit(":", 1) for e in redis_client.lrange(SENT_LOG, 0, -1)]

    # 1. No job lost, none sent twice.
    assert sorted(k for k, _ in records) == sorted(keys)

    # 2. The limit was never exceeded in any rolling window ...
    limit = settings.EMAIL_RATE_LIMIT
    window_ms = settings.EMAIL_RATE_WINDOW_SECONDS * 1000
    ts = sorted(int(ms) for _, ms in records)
    for i in range(len(ts) - limit):
        assert ts[i + limit] - ts[i] >= window_ms - TOLERANCE_MS, (
            f"{limit + 1} sends within {ts[i + limit] - ts[i]} ms around index {i}"
        )
    # ... and throttling really happened (the test is not passing vacuously).
    min_span = (TOTAL_JOBS // limit - 1) * window_ms
    assert ts[-1] - ts[0] >= min_span - TOLERANCE_MS

    # 3. The intentional failure was retried and then succeeded.
    failed_job = EmailJob.objects.get(idempotency_key=FAIL_ONCE_KEY)
    assert calls[FAIL_ONCE_KEY] == 2
    assert failed_job.attempts == 1
    assert failed_job.status == EmailJob.Status.SENT


def test_job_that_always_fails_ends_in_dead_letter(celery_worker_running, monkeypatch):
    calls = collections.Counter()

    def always_failing_provider(job):
        calls[job.idempotency_key] += 1
        raise ProviderError("simulated permanent failure")

    monkeypatch.setattr("mailer.tasks.send_via_provider", always_failing_provider)
    monkeypatch.setattr("mailer.tasks.MAX_PROVIDER_ATTEMPTS", 3)
    monkeypatch.setattr("mailer.tasks.MAX_BACKOFF_SECONDS", 1)

    enqueue_email("doomed-1", "x@example.com", "Hi", "Hello")

    assert wait_for(
        lambda: EmailJob.objects.get(idempotency_key="doomed-1").status == EmailJob.Status.DEAD,
        timeout=30,
    )
    job = EmailJob.objects.get(idempotency_key="doomed-1")
    assert job.attempts == 3
    assert calls["doomed-1"] == 3
    assert "simulated permanent failure" in job.last_error
