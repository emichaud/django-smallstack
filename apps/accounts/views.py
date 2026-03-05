"""
Views for the accounts app.
"""

from django.conf import settings as django_settings
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView

from .forms import SignupForm


class SignupView(CreateView):
    """
    View for user registration.
    After successful signup, logs the user in and redirects to home.
    """

    form_class = SignupForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        """Log in the user after successful registration."""
        response = super().form_valid(form)
        login(self.request, self.object)
        return response

    def dispatch(self, request, *args, **kwargs):
        """Redirect authenticated users to home. 404 if signup is disabled."""
        if not getattr(django_settings, "SMALLSTACK_SIGNUP_ENABLED", True):
            raise Http404
        if request.user.is_authenticated:
            return redirect("home")
        return super().dispatch(request, *args, **kwargs)
