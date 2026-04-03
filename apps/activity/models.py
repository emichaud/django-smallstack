"""Models for request activity tracking."""

from django.conf import settings
from django.db import models


class RequestLog(models.Model):
    """Logs individual HTTP requests for lightweight activity tracking."""

    path = models.CharField(max_length=2048)
    method = models.CharField(max_length=10)
    status_code = models.PositiveSmallIntegerField()
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    api_token = models.ForeignKey(
        "smallstack.APIToken",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_logs",
    )
    request_id = models.CharField(max_length=255, blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    response_time_ms = models.PositiveIntegerField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["path"]),
            models.Index(fields=["status_code"]),
        ]

    def __str__(self):
        return f"{self.method} {self.path} [{self.status_code}]"
