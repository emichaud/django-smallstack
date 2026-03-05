"""
Views for the profile app.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DetailView, UpdateView

from .forms import UserProfileForm
from .models import UserProfile

User = get_user_model()


class ProfileView(LoginRequiredMixin, DetailView):
    """View for displaying the current user's profile."""

    model = UserProfile
    template_name = "profile/profile.html"
    context_object_name = "profile"

    def get_object(self, queryset=None):
        """Get the current user's profile."""
        return get_object_or_404(UserProfile, user=self.request.user)


class ProfileEditView(LoginRequiredMixin, UpdateView):
    """View for editing the current user's profile."""

    model = UserProfile
    form_class = UserProfileForm
    template_name = "profile/profile_edit.html"
    context_object_name = "profile"
    success_url = reverse_lazy("profile")

    def get_object(self, queryset=None):
        """Get the current user's profile."""
        return get_object_or_404(UserProfile, user=self.request.user)

    def form_valid(self, form):
        """Add success message on form save."""
        messages.success(self.request, "Profile updated successfully.")
        return super().form_valid(form)


class ThemePreferenceView(LoginRequiredMixin, View):
    """Save theme preference via htmx POST."""

    def post(self, request):
        theme = request.POST.get("theme", "").strip()
        if theme in ("dark", "light"):
            profile = get_object_or_404(UserProfile, user=request.user)
            profile.theme_preference = theme
            profile.save(update_fields=["theme_preference"])
        return HttpResponse(status=204)


class ProfileDetailView(DetailView):
    """View for displaying any user's public profile."""

    model = UserProfile
    template_name = "profile/profile_detail.html"
    context_object_name = "profile"

    def get_object(self, queryset=None):
        """Get the profile by username from URL."""
        username = self.kwargs.get("username")
        user = get_object_or_404(User, username=username)
        return get_object_or_404(UserProfile, user=user)
