"""Explorer registration for profile models."""

from django.contrib import admin

from apps.explorer.registry import explorer
from apps.smallstack.displays import (
    DetailCardDisplay,
    DetailGridDisplay,
    SectionedFormDisplay,
    TableDisplay,
)

from .displays import ProfileCardDisplay, UserActivityDisplay
from .models import UserProfile


class UserProfileExplorerAdmin(admin.ModelAdmin):
    """Streamlined layout for Explorer — different from the full admin config.

    Demonstrates display palette on both list and detail views.
    """

    list_display = ("user", "display_name", "bio", "location", "created_at")
    list_per_page = 12

    # Toolbar: search + filters, shared across all displays (table, cards, etc.)
    search_fields = ("user__username", "display_name", "location")
    list_filter = ("theme_preference",)

    explorer_list_fields = ("user", "display_name", "location", "created_at")
    explorer_column_widths = {
        "user": "25%",
        "display_name": "25%",
        "location": "25%",
        "created_at": "25%",
    }

    # List: three displays
    explorer_displays = [
        TableDisplay,
        ProfileCardDisplay(),
    ]

    # Detail: two-column grid (default), card (photo + grid), activity chart
    explorer_detail_displays = [
        DetailGridDisplay,
        DetailCardDisplay(image_field="profile_photo"),
        UserActivityDisplay(),
    ]

    # Transforms apply in the basic table display (TableDisplay)
    explorer_field_transforms = {"bio": "preview"}

    # Form: sectioned layout for create/edit
    explorer_form_displays = [
        SectionedFormDisplay(
            sections=[
                ("Identity", None, ["display_name", "location"]),
                ("About", None, ["bio"]),
            ]
        ),
    ]


explorer.register(UserProfile, UserProfileExplorerAdmin, group="Accounts")
