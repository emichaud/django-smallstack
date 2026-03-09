"""Reusable view mixins for SmallStack."""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Mixin that restricts access to staff users."""

    def test_func(self):
        return self.request.user.is_staff
