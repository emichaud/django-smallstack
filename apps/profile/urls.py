"""
URL configuration for the profile app.
"""

from django.urls import path

from .views import (
    PalettePreferenceView,
    ProfileDetailView,
    ProfileEditView,
    ProfileView,
    ThemePreferenceView,
)

urlpatterns = [
    path("", ProfileView.as_view(), name="profile"),
    path("edit/", ProfileEditView.as_view(), name="profile_edit"),
    path("theme/", ThemePreferenceView.as_view(), name="theme_preference"),
    path("palette/", PalettePreferenceView.as_view(), name="palette_preference"),
    path("<str:username>/", ProfileDetailView.as_view(), name="profile_detail"),
]
