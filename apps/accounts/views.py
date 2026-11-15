"""
Views for the accounts app: signup, invite-by-email + accept, and passwordless
("email me a code") login.
"""

import logging
from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetConfirmView, PasswordResetView
from django.db.models import F
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views import View
from django.views.generic import CreateView, FormView

from apps.smallstack.mixins import StaffRequiredMixin

from .emails import (
    deliver_account_email,
    send_invite_now,
    send_login_code_message,
    send_login_code_now,
    unique_username_from_email,
)
from .forms import InviteUserForm, SignupForm, StyledSetPasswordForm
from .models import LoginCode

logger = logging.getLogger(__name__)

# We bypass authenticate() for invite-accept and passwordless login, so login()
# needs the backend named explicitly (the project configures two backends).
MODEL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _site_name() -> str:
    return getattr(django_settings, "SITE_NAME", getattr(django_settings, "BRAND_NAME", "SmallStack"))


class SignupView(CreateView):
    """User self-registration. Logs in and redirects home on success."""

    form_class = SignupForm
    template_name = "registration/signup.html"
    success_url = reverse_lazy("website:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("accounts: %s (pk=%s) signed up", self.object.get_username(), self.object.pk)
        login(self.request, self.object, backend=MODEL_BACKEND)
        return response

    def dispatch(self, request, *args, **kwargs):
        if not getattr(django_settings, "SMALLSTACK_SIGNUP_ENABLED", True):
            raise Http404
        if request.user.is_authenticated:
            return redirect("website:home")
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Invite by email
# ---------------------------------------------------------------------------
def _request_site_url(request) -> str:
    """The absolute base URL the request arrived on, for links in queued mail."""
    return request.build_absolute_uri("/").rstrip("/")


def send_invite_email(request, user, inviter=None):
    """Email ``user`` a one-click link to set their password and finish joining.

    Queued on the ``email`` queue (inline under DEBUG). The link's token is
    minted by the sender, never passed through the queue.
    """
    from .tasks import send_invite_email_task

    deliver_account_email(
        send_invite_email_task, send_invite_now, user.pk, str(inviter or ""), _request_site_url(request)
    )


def send_setup_or_reset(request, user) -> str | None:
    """Email ``user`` the right "set your password" link.

    Returns "invite" (user never set a password — resend the invite),
    "reset" (existing account — standard branded reset email), or None
    (no email address on file). Used by the staff "Send link" action.
    """
    if not user.email:
        return None
    if not user.has_usable_password():
        inviter = request.user.get_full_name() or request.user.get_username()
        send_invite_email(request, user, inviter=inviter)
        return "invite"

    from django.contrib.auth.forms import PasswordResetForm

    form = PasswordResetForm({"email": user.email})
    if not form.is_valid():
        return None
    form.save(
        request=request,
        use_https=request.is_secure(),
        from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", None),
        email_template_name="registration/password_reset_email.html",
        html_email_template_name="registration/password_reset_email_html.html",
        subject_template_name="registration/password_reset_subject.txt",
        extra_email_context={
            "site_name": _site_name(),
            "brand_name": getattr(django_settings, "BRAND_NAME", "SmallStack"),
            "brand_accent": getattr(django_settings, "BRAND_EMAIL_ACCENT", "#10b981"),
        },
    )
    return "reset"


#: Inviting creates an active account, so it asks what the User Manager's
#: create page asks (``accounts.add_user``); making the invitee staff also
#: needs ``accounts.change_user``, the permission that sets the staff flag.
INVITE_PERMISSION = "accounts.add_user"
INVITE_STAFF_PERMISSION = "accounts.change_user"


def can_invite(user) -> bool:
    """Whether ``user`` may use the invite page (active staff with ``add_user``)."""
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and user.is_staff
        and user.has_perm(INVITE_PERMISSION)
    )


class InviteUserView(StaffRequiredMixin, FormView):
    """Staff create a user by email; the user sets their own password via link.

    Needs ``accounts.add_user`` (superusers hold it); the "Grant staff access"
    box is offered only with ``accounts.change_user`` as well, and a posted
    ``is_staff`` is ignored without it. The form has no superuser field, so an
    invite never creates a superuser."""

    template_name = "registration/invite_form.html"
    form_class = InviteUserForm
    success_url = reverse_lazy("manage/users-list")

    def test_func(self) -> bool:
        return can_invite(self.request.user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not self.request.user.has_perm(INVITE_STAFF_PERMISSION):
            form.fields.pop("is_staff", None)
        return form

    def form_valid(self, form):
        User = get_user_model()
        email = form.cleaned_data["email"]
        user = User(
            username=unique_username_from_email(email),
            email=email,
            first_name=form.cleaned_data.get("first_name", ""),
            last_name=form.cleaned_data.get("last_name", ""),
            is_staff=form.cleaned_data.get("is_staff", False),
            is_active=True,
        )
        user.set_unusable_password()
        user.save()
        inviter = self.request.user.get_full_name() or self.request.user.get_username()
        send_invite_email(self.request, user, inviter=inviter)
        logger.info(
            "accounts: %s invited %s (pk=%s, staff=%s)", self.request.user, user.get_username(), user.pk, user.is_staff
        )
        messages.success(self.request, f"Invitation sent to {email}.")
        return super().form_valid(form)


class AcceptInviteView(View):
    """Public: validate an invite/set-password token and let the user pick a password."""

    template_name = "registration/invite_accept.html"

    def _load(self, uidb64, token):
        User = get_user_model()
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
        valid = user is not None and default_token_generator.check_token(user, token)
        return user, valid

    def get(self, request, uidb64, token):
        user, valid = self._load(uidb64, token)
        form = StyledSetPasswordForm(user) if valid else None
        return render(request, self.template_name, {"valid": valid, "form": form})

    def post(self, request, uidb64, token):
        user, valid = self._load(uidb64, token)
        if not valid:
            return render(request, self.template_name, {"valid": False, "form": None})
        form = StyledSetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            logger.info("accounts: %s (pk=%s) accepted an invite and set a password", user.get_username(), user.pk)
            login(request, user, backend=MODEL_BACKEND)
            messages.success(request, "Your password is set — welcome!")
            return redirect("website:home")
        return render(request, self.template_name, {"valid": True, "form": form})


# ---------------------------------------------------------------------------
# Passwordless ("email me a code") login
# ---------------------------------------------------------------------------
def send_login_code_email(request, user, code):
    """Send a known ``code`` to ``user`` right now, in the request.

    Kept for callers that mint their own code. The passwordless view queues
    instead (``send_login_code``), so the raw code never reaches the task table.
    """
    send_login_code_message(user, code, _request_site_url(request))


def send_login_code(request, login_code):
    """Queue the sign-in email for ``login_code`` (inline under DEBUG)."""
    from .tasks import send_login_code_task

    deliver_account_email(send_login_code_task, send_login_code_now, login_code.pk, _request_site_url(request))


class PasswordlessLoginView(View):
    """Two-step email-code login. Step 1: email -> code sent. Step 2: code -> in.

    Does not reveal whether an email is registered; codes are hashed, expiring,
    single-use, attempt-limited, and rate-limited to one per minute per user.
    """

    template_name = "registration/passwordless_login.html"
    RESEND_THROTTLE_SECONDS = 60

    def dispatch(self, request, *args, **kwargs):
        if not getattr(django_settings, "SMALLSTACK_PASSWORDLESS_LOGIN", False):
            raise Http404
        if request.user.is_authenticated:
            return redirect("website:home")
        return super().dispatch(request, *args, **kwargs)

    def _render(self, request, step, **ctx):
        return render(request, self.template_name, {"step": step, **ctx})

    def get(self, request):
        email = request.session.get("pwl_email")
        return self._render(request, "code" if email else "email", email=email)

    def post(self, request):
        action = request.POST.get("action")
        User = get_user_model()

        if action == "restart":
            request.session.pop("pwl_email", None)
            return redirect("accounts:passwordless_login")

        if action == "request":
            email = (request.POST.get("email") or "").strip().lower()
            if not email:
                return self._render(request, "email", error="Please enter your email address.")
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user and user.email:
                now = timezone.now()
                cutoff = now - timedelta(seconds=self.RESEND_THROTTLE_SECONDS)
                recent = user.login_codes.filter(consumed=False, created_at__gte=cutoff).exists()
                # Per-account hourly cap: each code allows MAX_ATTEMPTS guesses,
                # so without it an attacker re-requesting every minute gets
                # ~7,200 guesses/day at a 6-digit code.
                hourly_cap = int(getattr(django_settings, "SMALLSTACK_LOGIN_CODES_PER_HOUR", 5))
                issued_last_hour = user.login_codes.filter(created_at__gte=now - timedelta(hours=1)).count()
                if not recent and issued_last_hour < hourly_cap:
                    login_code, _ = LoginCode.issue(user)
                    send_login_code(request, login_code)
                    logger.info("accounts: sign-in code issued for %s (pk=%s)", user.get_username(), user.pk)
                elif issued_last_hour >= hourly_cap:
                    # The cap is what stops code guessing; hitting it is worth a look.
                    logger.warning(
                        "accounts: sign-in code refused for %s (pk=%s): %s codes in the last hour",
                        user.get_username(), user.pk, issued_last_hour,
                    )
            request.session["pwl_email"] = email
            return self._render(
                request,
                "code",
                email=email,
                info=f"If an account exists for {email}, we've emailed a sign-in code.",
            )

        if action == "verify":
            email = request.session.get("pwl_email") or (request.POST.get("email") or "").strip().lower()
            code = (request.POST.get("code") or "").strip()
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user and code:
                lc = user.login_codes.filter(consumed=False).order_by("-created_at").first()
                # Spend an attempt atomically *before* checking: a
                # read-then-save counter let parallel guesses all pass the
                # attempt limit. Likewise, consuming is a conditional UPDATE so
                # one code can't log in two concurrent requests.
                if lc and lc.is_live and LoginCode.objects.filter(
                    pk=lc.pk, consumed=False, attempts__lt=LoginCode.MAX_ATTEMPTS, expires_at__gt=timezone.now()
                ).update(attempts=F("attempts") + 1):
                    if lc.check_code(code) and LoginCode.objects.filter(pk=lc.pk, consumed=False).update(
                        consumed=True
                    ):
                        request.session.pop("pwl_email", None)
                        login(request, user, backend=MODEL_BACKEND)
                        messages.success(request, "You're signed in.")
                        return redirect("website:home")
            if user:
                logger.info("accounts: sign-in code rejected for %s (pk=%s)", user.get_username(), user.pk)
            return self._render(
                request, "code", email=email, error="That code is invalid or has expired."
            )

        return self._render(request, "email")


# ---------------------------------------------------------------------------
# Password reset, logged
# ---------------------------------------------------------------------------
class LoggedPasswordResetView(PasswordResetView):
    """Django's reset request, plus a log line. The page still never says
    whether the address has an account; the staff-only log does, so a run of
    requests for unknown addresses is visible."""

    def form_valid(self, form):
        email = form.cleaned_data.get("email", "")
        matches = [u.pk for u in form.get_users(email)]
        logger.info("accounts: password reset requested (%s matching account%s: %s)",
                    len(matches), "" if len(matches) == 1 else "s", matches)
        return super().form_valid(form)


class LoggedPasswordResetConfirmView(PasswordResetConfirmView):
    """Django's set-new-password step, plus a log line when it succeeds."""

    def form_valid(self, form):
        response = super().form_valid(form)
        logger.info("accounts: %s (pk=%s) reset their password", form.user.get_username(), form.user.pk)
        return response
