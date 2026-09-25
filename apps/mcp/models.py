"""MCP models. OAuthAuthorizationCode lives here; APIToken stays in smallstack."""

from django.conf import settings
from django.db import models


class OAuthAuthorizationCode(models.Model):
    """One-shot, PKCE-bound authorization code minted by the consent page.

    Exchanged once for a Bearer token via POST /mcp/oauth/token. After
    redemption, `used_at` is set and `raw_key` is cleared so the row remains
    for audit without leaking material.
    """

    code = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mcp_oauth_codes",
    )
    api_token = models.ForeignKey(
        "smallstack.APIToken",
        on_delete=models.CASCADE,
        related_name="mcp_oauth_codes",
    )
    raw_key = models.CharField(max_length=128, blank=True, default="")
    redirect_uri = models.URLField()
    code_challenge = models.CharField(max_length=128)
    code_challenge_method = models.CharField(max_length=10, default="S256")
    scope = models.CharField(max_length=200, blank=True, default="")
    client_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"OAuthCode({self.code[:8]}… → {self.user})"


def expire_unredeemed_codes() -> int:
    """Scrub codes that outlived their TTL without being redeemed.

    The raw bearer key waits on the row between consent and ``/token``; if the
    client never comes back, it would sit there in plaintext indefinitely, and
    the token it names — never delivered to anyone — would stay live. Clear the
    key and deactivate that token. Called opportunistically from the OAuth
    views, so no cron entry is needed. (Audit 2026-09-13, C9b.)
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.smallstack.models import APIToken

    ttl = int(getattr(settings, "MCP_OAUTH_CODE_TTL_SECONDS", 600))
    stale = OAuthAuthorizationCode.objects.filter(
        used_at__isnull=True,
        created_at__lt=timezone.now() - timedelta(seconds=ttl),
    ).exclude(raw_key="")
    token_ids = list(stale.values_list("api_token_id", flat=True))
    if not token_ids:
        return 0
    APIToken.objects.filter(pk__in=token_ids, token_type="oauth", is_active=True).update(
        is_active=False, revoked_at=timezone.now()
    )
    return stale.update(raw_key="")
