import time

from mailer.models import EmailJob
from mailer.services import enqueue_email


def wait_for(predicate, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def test_one_job_is_sent(celery_worker_running, monkeypatch):
    sent = []
    monkeypatch.setattr("mailer.tasks.send_via_provider", lambda job: sent.append(job.idempotency_key))

    enqueue_email("t-1", "a@example.com", "Hi", "Hello")

    assert wait_for(lambda: EmailJob.objects.get(idempotency_key="t-1").status == "SENT")
    assert sent == ["t-1"]
