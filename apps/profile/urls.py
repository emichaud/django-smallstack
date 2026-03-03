"""
URL configuration for the profile app.
"""

from django.urls import path

from .views import ProfileDetailView, ProfileEditView, ProfileView

urlpatterns = [
    path("", ProfileView.as_view(), name="profile"),
    path("edit/", ProfileEditView.as_view(), name="profile_edit"),
    path("<str:username>/", ProfileDetailView.as_view(), name="profile_detail"),
]
