from .models import EmailJob
from .tasks import send_email_task


def enqueue_email(idempotency_key, recipient, subject, body):
    """Create the job row and queue it. Returns (job, created).

    If queueing fails (for example Redis is down) the row is removed and the
    error propagates, so the API can answer 503 instead of pretending the
    email was accepted.
    """
    job, created = EmailJob.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={"recipient": recipient, "subject": subject, "body": body},
    )
    if created:
        try:
            send_email_task.delay(job.id)
        except Exception:
            job.delete()
            raise
    return job, created
