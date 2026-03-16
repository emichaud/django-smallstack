"""
Admin configuration for UserProfile model.
"""

from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin configuration for UserProfile with nice display and fieldsets."""

    list_display = ("get_username", "display_name", "bio", "location", "created_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("user__username", "display_name", "location", "bio")
    readonly_fields = ("created_at", "updated_at", "user")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "User",
            {
                "fields": ("user",),
            },
        ),
        (
            "Profile Information",
            {
                "fields": ("display_name", "bio", "location", "website", "date_of_birth", "timezone"),
            },
        ),
        (
            "Photos",
            {
                "fields": ("profile_photo", "background_photo"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def get_username(self, obj):
        """Display the username from the related User."""
        return obj.user.username

    get_username.short_description = "Username"
    get_username.admin_order_field = "user__username"
