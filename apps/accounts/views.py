"""
Views for the accounts app: signup, invite-by-email + accept, and passwordless
("email me a code") login.
"""

from datetime import timedelta

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.tokens import default_token_generator
from django.db.models import F
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views import View
from django.views.generic import CreateView, FormView

from apps.smallstack.mixins import StaffRequiredMixin

from .emails import send_branded_email, unique_username_from_email
from .forms import InviteUserForm, SignupForm, StyledSetPasswordForm
from .models import LoginCode

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
def send_invite_email(request, user, inviter=None):
    """Email ``user`` a one-click link to set their password and finish joining."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    accept_url = request.build_absolute_uri(
        reverse("accounts:invite_accept", kwargs={"uidb64": uid, "token": token})
    )
    send_branded_email(
        subject=f"You're invited to {_site_name()}",
        template="email/invite.html",
        context={
            "user": user,
            "accept_url": accept_url,
            "inviter": inviter or "",
            "preheader": f"You've been invited to {_site_name()}. Set your password to get started.",
        },
        to=user.email,
        request=request,
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


class InviteUserView(StaffRequiredMixin, FormView):
    """Staff create a user by email; the user sets their own password via link."""

    template_name = "registration/invite_form.html"
    form_class = InviteUserForm
    success_url = reverse_lazy("manage/users-list")

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
            login(request, user, backend=MODEL_BACKEND)
            messages.success(request, "Your password is set — welcome!")
            return redirect("website:home")
        return render(request, self.template_name, {"valid": True, "form": form})


# ---------------------------------------------------------------------------
# Passwordless ("email me a code") login
# ---------------------------------------------------------------------------
def send_login_code_email(request, user, code):
    send_branded_email(
        subject=f"Your {_site_name()} sign-in code: {code}",
        template="email/login_code.html",
        context={
            "user": user,
            "code": code,
            "ttl_minutes": max(1, getattr(django_settings, "SMALLSTACK_LOGIN_CODE_TTL", 600) // 60),
            "preheader": f"Your {_site_name()} sign-in code is {code}.",
        },
        to=user.email,
        request=request,
    )


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
                # ~7,200 guesses/day at a 6-digit code. (Audit 2026-09-13, H3.)
                hourly_cap = int(getattr(django_settings, "SMALLSTACK_LOGIN_CODES_PER_HOUR", 5))
                issued_last_hour = user.login_codes.filter(created_at__gte=now - timedelta(hours=1)).count()
                if not recent and issued_last_hour < hourly_cap:
                    _, code = LoginCode.issue(user)
                    send_login_code_email(request, user, code)
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
                # one code can't log in two concurrent requests. (Audit H3.)
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
            return self._render(
                request, "code", email=email, error="That code is invalid or has expired."
            )

        return self._render(request, "email")
