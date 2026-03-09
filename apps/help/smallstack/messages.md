# Messages

SmallStack styles Django's built-in messages framework with four notification types. Messages auto-dismiss after 5 seconds.

## Message Types

```html
<div class="message success">
    <span>Operation completed successfully!</span>
</div>

<div class="message info">
    <span>Here's some helpful information.</span>
</div>

<div class="message warning">
    <span>Please review before continuing.</span>
</div>

<div class="message error">
    <span>Something went wrong!</span>
</div>
```

## Using in Views

Add messages in your Django views with `django.contrib.messages`:

```python
from django.contrib import messages

def my_view(request):
    messages.success(request, "Profile updated!")
    messages.info(request, "Check your email for confirmation.")
    messages.warning(request, "Your session expires in 5 minutes.")
    messages.error(request, "Could not save changes.")
    return redirect("profile")
```

Messages are rendered automatically by `base.html` — no template changes needed.

## Auto-Dismiss

Messages slide in and automatically dismiss after 5 seconds. This behavior is built into SmallStack's base JavaScript. To keep a message visible (no auto-dismiss), add `style="animation: none;"` to the message div.

## Where SmallStack Uses Messages

- **Profile save** — success confirmation
- **Login / Logout** — session messages
- **Form validation** — error feedback
