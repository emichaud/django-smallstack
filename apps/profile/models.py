"""
UserProfile model for extended user information.
"""

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models


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
