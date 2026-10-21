import os
import smtplib
import time

from django.core.mail import send_mail


class ProviderError(Exception):
    """Transient failure from the email provider (timeout, 5xx)."""


def send_via_provider(job):
    """Send one email through Django's configured EMAIL_BACKEND."""
    # Demo only: simulate a slow provider so a worker can be killed mid-task.
    delay = float(os.environ.get("DEMO_SEND_DELAY", "0"))
    if delay:
        time.sleep(delay)
    try:
        send_mail(
            subject=job.subject,
            message=job.body,
            from_email="noreply@example.com",
            recipient_list=[job.recipient],
            fail_silently=False,
        )
    except (OSError, smtplib.SMTPException) as exc:
        raise ProviderError(str(exc)) from exc
