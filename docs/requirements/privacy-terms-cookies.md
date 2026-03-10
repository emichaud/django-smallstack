# Privacy, Terms & Cookie Consent — v1.0 Requirement

Every production web app needs privacy policy, terms of service, and cookie consent.
SmallStack should ship these so downstream projects don't reinvent them.

## Goals

- Zero-config for the common case — works out of the box with sensible defaults
- Customizable content — users replace example text with their own
- Settings-driven — toggle on/off and configure via `BRAND_*` settings
- No heavyweight consent management — keep it simple for small apps

## Components

### 1. Legal Pages (Privacy Policy & Terms of Service)

**Approach:** Markdown pages rendered through the existing help/content system.

- Ship example `privacy-policy.md` and `terms-of-service.md` in a content directory
- Render with the standard SmallStack layout (extends `base.html`)
- Accessible without login (public pages)
- URL routes: `/privacy/` and `/terms/` (or configurable)

**Settings:**
```python
# config/settings/base.py
BRAND_PRIVACY_URL = "/privacy/"      # set to None to disable footer link
BRAND_TERMS_URL = "/terms/"          # set to None to disable footer link
```

**Template integration:**
- Footer links auto-render when URLs are configured
- Links appear in signup/registration flow (checkbox or notice)
- Links appear in the cookie consent banner

### 2. Cookie Consent Banner

**Approach:** Template include in `base.html`, vanilla JS, localStorage for persistence.

- Banner appears at bottom of page for first-time visitors
- "Accept" button dismisses and sets `localStorage` flag
- Optional "Learn more" link points to privacy policy
- Does NOT reload page or block interaction
- Respects `Do Not Track` header (optional enhancement)

**No cookie categorization in v1.** Most small apps set a session cookie and maybe
analytics — the full GDPR category picker (functional/analytics/marketing) is
over-engineered for the target audience. Can be added in a future release if needed.

**Implementation:**
```html
<!-- templates/smallstack/includes/cookie_banner.html -->
{% if not request.COOKIES.cookie_consent %}
<div id="cookie-banner" class="cookie-banner">
    <p>This site uses cookies. <a href="{{ brand.privacy_url }}">Learn more</a></p>
    <button onclick="acceptCookies()">Accept</button>
</div>
{% endif %}
```

```javascript
function acceptCookies() {
    localStorage.setItem('cookie_consent', 'accepted');
    document.getElementById('cookie-banner').remove();
    // Also set a cookie so the server can skip rendering on next request
    document.cookie = 'cookie_consent=accepted; path=/; max-age=31536000';
}
```

**Styling:**
- Fixed bottom bar, full width
- Uses theme CSS variables (`--card-bg`, `--border-color`, `--primary`)
- Dark/light mode compatible
- Dismissible — doesn't block content

### 3. Footer Links

**Approach:** Add to the existing footer partial in `base.html`.

- Show Privacy Policy and Terms links when configured
- Show copyright notice with `BRAND_NAME`
- Example: `© 2026 MyApp · Privacy · Terms`

### 4. Registration Integration

- Add a notice or checkbox on the signup page: "By signing up, you agree to our Terms and Privacy Policy"
- Links open in new tab
- Not a hard blocker for signup — just a notice (configurable)

## File Structure

```
apps/help/content/legal/
├── _config.yaml          # Section config for legal pages
├── privacy-policy.md     # Example privacy policy (user customizes)
└── terms-of-service.md   # Example terms of service (user customizes)

templates/smallstack/includes/
└── cookie_banner.html    # Cookie consent banner partial

config/settings/base.py   # BRAND_PRIVACY_URL, BRAND_TERMS_URL settings
```

## Settings Summary

| Setting | Default | Purpose |
|---------|---------|---------|
| `BRAND_PRIVACY_URL` | `"/privacy/"` | Privacy policy page URL (None to disable) |
| `BRAND_TERMS_URL` | `"/terms/"` | Terms of service page URL (None to disable) |
| `BRAND_COOKIE_BANNER` | `True` | Show cookie consent banner |
| `BRAND_SIGNUP_TERMS_NOTICE` | `True` | Show terms notice on signup page |

## What Ships vs. What the User Customizes

**Ships (don't touch):**
- Cookie banner template and JS
- Footer link rendering logic
- Settings and context processor integration
- URL routing for legal pages

**User customizes:**
- Privacy policy content (edit the .md file)
- Terms of service content (edit the .md file)
- Settings values (URLs, toggle banner on/off)

## Out of Scope for v1.0

- Cookie categorization (functional/analytics/marketing)
- Consent logging to database
- GDPR data export/deletion workflows
- Cookie scanning and auto-detection
- Geolocation-based consent requirements

These can be considered for a future release or SmallStack Pro.

## Questions to Resolve

1. **Legal pages location:** Render via the help app's content system (reuse existing Markdown pipeline) or as standalone templates in a new `legal` app? Help system is simpler but couples legal content to docs.
2. **Cookie check mechanism:** localStorage + cookie (client-side fast, server skips banner render) vs. database model (trackable, but heavier). Recommend localStorage + cookie for v1.
3. **Registration checkbox vs. notice:** Checkbox that must be checked, or just a text notice with links? Notice is less friction, checkbox is more legally defensible. Default to notice, make it configurable.
