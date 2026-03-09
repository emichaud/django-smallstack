"""
UserProfile model for extended user information.
"""

import zoneinfo

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

# Common timezone choices grouped by region for the UI dropdown.
# Covers major cities; the full IANA database is available via zoneinfo.
TIMEZONE_CHOICES = [
    ("", "Use system default"),
    (
        "Americas",
        [
            ("America/New_York", "Eastern Time (New York)"),
            ("America/Chicago", "Central Time (Chicago)"),
            ("America/Denver", "Mountain Time (Denver)"),
            ("America/Los_Angeles", "Pacific Time (Los Angeles)"),
            ("America/Anchorage", "Alaska (Anchorage)"),
            ("Pacific/Honolulu", "Hawaii (Honolulu)"),
            ("America/Toronto", "Toronto"),
            ("America/Vancouver", "Vancouver"),
            ("America/Mexico_City", "Mexico City"),
            ("America/Sao_Paulo", "S\u00e3o Paulo"),
            ("America/Argentina/Buenos_Aires", "Buenos Aires"),
            ("America/Bogota", "Bogot\u00e1"),
            ("America/Lima", "Lima"),
        ],
    ),
    (
        "Europe",
        [
            ("Europe/London", "London"),
            ("Europe/Dublin", "Dublin"),
            ("Europe/Paris", "Paris"),
            ("Europe/Berlin", "Berlin"),
            ("Europe/Amsterdam", "Amsterdam"),
            ("Europe/Madrid", "Madrid"),
            ("Europe/Rome", "Rome"),
            ("Europe/Zurich", "Zurich"),
            ("Europe/Stockholm", "Stockholm"),
            ("Europe/Warsaw", "Warsaw"),
            ("Europe/Athens", "Athens"),
            ("Europe/Moscow", "Moscow"),
            ("Europe/Istanbul", "Istanbul"),
        ],
    ),
    (
        "Asia & Pacific",
        [
            ("Asia/Dubai", "Dubai"),
            ("Asia/Kolkata", "India (Kolkata)"),
            ("Asia/Shanghai", "China (Shanghai)"),
            ("Asia/Tokyo", "Tokyo"),
            ("Asia/Seoul", "Seoul"),
            ("Asia/Singapore", "Singapore"),
            ("Asia/Hong_Kong", "Hong Kong"),
            ("Asia/Bangkok", "Bangkok"),
            ("Asia/Jakarta", "Jakarta"),
            ("Australia/Sydney", "Sydney"),
            ("Australia/Melbourne", "Melbourne"),
            ("Australia/Perth", "Perth"),
            ("Pacific/Auckland", "Auckland"),
        ],
    ),
    (
        "Africa & Middle East",
        [
            ("Africa/Cairo", "Cairo"),
            ("Africa/Lagos", "Lagos"),
            ("Africa/Johannesburg", "Johannesburg"),
            ("Africa/Nairobi", "Nairobi"),
            ("Asia/Jerusalem", "Jerusalem"),
            ("Asia/Riyadh", "Riyadh"),
        ],
    ),
]


def validate_image_size(image):
    """Validate that uploaded image is not too large (max 5MB)."""
    from django.core.exceptions import ValidationError

    max_size = 5 * 1024 * 1024  # 5MB
    if image.size > max_size:
        raise ValidationError(f"Image file too large. Maximum size is {max_size // (1024 * 1024)}MB.")


class UserProfile(models.Model):
    """
    Extended user profile with additional fields.
    Auto-created via post_save signal when a User is created.
    """

    THEME_CHOICES = [
        ("dark", "Dark"),
        ("light", "Light"),
    ]

    COLOR_PALETTE_CHOICES = [
        ("", "System Default"),
        ("django", "Django"),
        ("high-contrast", "High Contrast"),
        ("dark-blue", "Blue"),
        ("orange", "Orange"),
        ("purple", "Purple"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    theme_preference = models.CharField(
        max_length=10,
        choices=THEME_CHOICES,
        default="dark",
        help_text="Preferred color theme",
    )
    color_palette = models.CharField(
        max_length=20,
        choices=COLOR_PALETTE_CHOICES,
        default="",
        blank=True,
        help_text="Color palette override (blank = system default)",
    )
    profile_photo = models.ImageField(
        upload_to="profiles/photos/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "gif", "webp"]),
            validate_image_size,
        ],
        help_text="Profile photo (max 5MB, jpg/png/gif/webp)",
    )
    background_photo = models.ImageField(
        upload_to="profiles/backgrounds/",
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "gif", "webp"]),
            validate_image_size,
        ],
        help_text="Background photo (max 5MB, jpg/png/gif/webp)",
    )
    display_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Name to display publicly",
    )
    bio = models.TextField(
        blank=True,
        help_text="A short bio about yourself",
    )
    location = models.CharField(
        max_length=100,
        blank=True,
        help_text="Where you're located",
    )
    website = models.URLField(
        blank=True,
        help_text="Your personal website",
    )
    date_of_birth = models.DateField(
        blank=True,
        null=True,
        help_text="Your date of birth",
    )
    timezone = models.CharField(
        max_length=50,
        blank=True,
        default="",
        choices=TIMEZONE_CHOICES,
        help_text="Your local timezone for displaying dates and times",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "user profile"
        verbose_name_plural = "user profiles"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Profile for {self.user.username}"

    def get_display_name(self):
        """Return display name or username as fallback."""
        return self.display_name or self.user.username

    def get_timezone(self):
        """Return the user's timezone as a ZoneInfo object.

        Falls back to the Django TIME_ZONE setting if the user hasn't set one.
        """
        tz_name = self.timezone or settings.TIME_ZONE
        return zoneinfo.ZoneInfo(tz_name)

    def to_local_time(self, dt):
        """Convert a UTC datetime to the user's local timezone.

        Usage in views:
            local_dt = request.user.profile.to_local_time(record.created_at)

        Usage in templates (via the |localtime filter — see theme_tags):
            {{ record.created_at|user_localtime:request }}
        """
        return dt.astimezone(self.get_timezone())
