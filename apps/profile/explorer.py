"""Explorer registration for profile models."""

from django.contrib import admin

from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    CardDisplay,
    DetailCardDisplay,
    DetailTableDisplay,
    Table2Display,
    TableDisplay,
)

from .models import UserProfile


class UserProfileExplorerAdmin(admin.ModelAdmin):
    """Streamlined layout for Explorer — different from the full admin config.

    Demonstrates display palette on both list and detail views.
    """

    list_display = ("user", "display_name", "bio", "location", "created_at")
    list_per_page = 12

    # List: three displays
    explorer_displays = [
        Table2Display,
        TableDisplay,
        CardDisplay(title_field="user", subtitle_field="created_at"),
    ]

    # Detail: table (classic) and card (grid) layouts
    explorer_detail_displays = [DetailTableDisplay, DetailCardDisplay(image_field="profile_photo")]

    # Transforms apply in the basic table display (TableDisplay)
    explorer_field_transforms = {"bio": "preview"}


explorer.register(UserProfile, UserProfileExplorerAdmin, group="Users")
