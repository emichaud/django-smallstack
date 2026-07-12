# Security Policy

## Supported versions

SmallStack is a starter framework that downstream projects clone and build on. Security fixes
land on the latest release line; there is no long-term backport program pre-1.0.

| Version | Supported |
|---|---|
| Latest release (`main`) | ✅ |
| Older tagged releases | ⚠️ Best-effort — upgrade to the latest recommended |

**Baseline requirements:** Python ≥ 3.12, Django ≥ 6.0. Running on unsupported Python/Django
versions is not covered by this policy.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report privately via one of:

- GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  ("Report a vulnerability" in the repository's **Security** tab), or
- Email the maintainer at **emichaud@gmail.com** with `[SmallStack Security]` in the subject.

Please include:

- A description of the vulnerability and its impact.
- Steps to reproduce (proof-of-concept, affected endpoint/setting, or minimal repro).
- The SmallStack version / commit and your Python + Django versions.

You can expect an initial acknowledgement within a few business days. Once a fix is prepared we
will coordinate a disclosure timeline with you and credit you in the release notes unless you
prefer to remain anonymous.

## Scope

In scope: the base framework in this repository (`apps/`, `config/`, deployment config). Out of
scope: vulnerabilities in third-party dependencies (report those upstream), and issues that
require a misconfiguration explicitly warned against in the docs.

## Security posture (what ships by default)

SmallStack ships production-hardened defaults, including:

- Hashed API tokens; `django-axes` login-attempt lockout.
- HSTS (with preload), secure/HTTP-only cookies, and `SECRET_KEY` that fails loud if unset in production.
- A Content-Security-Policy via `django-csp` (see `config/settings/base.py`).
- Per-view auth via `LoginRequiredMixin` / `StaffRequiredMixin`, and OAuth 2.0 + PKCE for MCP.

When adapting SmallStack, review `config/settings/production.py` and tighten the CSP for your
own inline-script/style needs before going live.
