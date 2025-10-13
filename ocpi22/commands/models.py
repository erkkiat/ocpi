from django.db import models


class CallBackExecutionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class CallBacks(models.Model):
    session = models.ForeignKey(
        "ocpi22.Session",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="callbacks",
    )
    callback_url = models.URLField(max_length=500)
    execution_status = models.CharField(
        max_length=20,
        choices=CallBackExecutionStatus.choices,
        default=CallBackExecutionStatus.PENDING,
    )

    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    authorization_reference = models.CharField(max_length=255)
    response_status_code = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "callbacks"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["execution_status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["session"]),
        ]

    def __str__(self):
        return f"Callback {self.id} - {self.callback_url} ({self.execution_status})"
