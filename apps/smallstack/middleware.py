"""
SmallStack middleware.
"""

import zoneinfo

from django.conf import settings
from django.utils import timezone


class TimezoneMiddleware:
    """Activate the user's timezone for the duration of each request.

    When a logged-in user has a timezone set on their profile, Django's
    template filters (like |date) will automatically display datetimes in
    that timezone.  Falls back to the system TIME_ZONE setting.

    Caches resolved timezone info on the request object so template tags
    can access it without repeated database queries:
        request._tz_user    – ZoneInfo for display (user or server fallback)
        request._tz_server  – ZoneInfo for server TIME_ZONE
        request._tz_differs – True when user TZ ≠ server TZ
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        server_tz = zoneinfo.ZoneInfo(settings.TIME_ZONE)
        user_tz = server_tz

        if hasattr(request, "user") and request.user.is_authenticated:
            try:
                user_tz = request.user.profile.get_timezone()
            except Exception:
                pass

        # Cache on request for template tags
        request._tz_user = user_tz
        request._tz_server = server_tz
        request._tz_differs = str(user_tz) != str(server_tz)

        timezone.activate(user_tz)

        response = self.get_response(request)
        return response
