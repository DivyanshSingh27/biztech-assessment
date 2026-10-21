from django.db import models


class EmailJob(models.Model):
    """One email to send. Doubles as the idempotency record and the dead-letter store."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        SENT = "SENT"
        DEAD = "DEAD"

    idempotency_key = models.CharField(max_length=64, unique=True)
    recipient = models.EmailField()
    subject = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)  # provider attempts only
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"EmailJob({self.idempotency_key}, {self.status})"
