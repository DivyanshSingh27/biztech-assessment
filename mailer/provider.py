import smtplib

from django.core.mail import send_mail


class ProviderError(Exception):
    """Transient failure from the email provider (timeout, 5xx)."""


def send_via_provider(job):
    """Send one email through Django's configured EMAIL_BACKEND."""
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
