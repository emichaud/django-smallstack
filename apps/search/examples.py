"""Real-world SearchBuilder integration examples for SmallStack models.

These examples demonstrate how to implement SearchBuilder on actual CRUDViews
with realistic patterns: filtering, computed fields, multiple variants.

All examples assume the underlying models exist in the project.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

# ============================================================================
# Example 1: User Search with Admin/Public Variants
# ============================================================================

class UserSearchBuilderExample:
    """SearchBuilder for User model with admin/public/api variants.

    Demonstrates:
    - Multiple variants (admin, public, api)
    - Filtering by is_active
    - Computed fields (account_age, permissions_count)
    - Variant-specific field exposure (hide email in public)
    """

    def get_search_variants(self) -> dict[str, str]:
        """Three variants for different contexts."""
        return {
            "admin": "Full user profile for admin panel (includes email, is_staff)",
            "public": "Public profile view (no email or staff status)",
            "api": "Structured JSON for agents (includes computed fields)"
        }

    def transform_hit(self, obj: Any, variant: str = "admin") -> dict[str, Any]:
        """Transform user object for each variant.

        obj: User model instance
        variant: "admin", "public", or "api"
        """
        base = {
            "id": obj.id,
            "display": obj.get_full_name() or obj.username,
            "username": obj.username,
        }

        if variant == "public":
            # Public variant: minimal exposure
            base["subtitle"] = f"Member since {obj.date_joined.year}" if obj.date_joined else "Member (date unknown)"
            return base

        elif variant == "api":
            # API variant: structured for agents
            base["email"] = obj.email
            base["is_staff"] = obj.is_staff
            base["is_active"] = obj.is_active
            base["account_age_days"] = (timezone.now() - obj.date_joined).days if obj.date_joined else None
            # Computed: is_admin
            base["is_admin"] = obj.is_staff and obj.is_superuser
            # Computed: groups count
            base["groups_count"] = obj.groups.count() if hasattr(obj, 'groups') else 0
            return base

        else:  # admin (default)
            # Admin variant: full detail
            base["email"] = obj.email
            base["subtitle"] = obj.email
            base["is_staff"] = obj.is_staff
            base["is_active"] = obj.is_active
            base["last_login"] = obj.last_login.isoformat() if obj.last_login else None
            base["date_joined"] = obj.date_joined.isoformat() if obj.date_joined else None
            return base

    def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
        """Only index active users."""
        return qs.filter(is_active=True)

    def get_ranking_weights(self) -> dict[str, int]:
        """Username matches are most important."""
        return {
            "username": 3,
            "first_name": 2,
            "last_name": 2,
            "email": 1
        }


# ============================================================================
# Example 2: Activity Log with Time-Based Filtering and Duration Computation
# ============================================================================

class ActivityLogSearchBuilderExample:
    """SearchBuilder for activity log with recent-items-only and computed duration.

    Demonstrates:
    - Time-based filtering (last 30 days)
    - Computed field (duration in human-readable format)
    - Summary vs detail variants
    - Filter applied at index time
    """

    def get_search_variants(self) -> dict[str, str]:
        """Two variants: quick summary and detailed."""
        return {
            "summary": "Activity type + timestamp (quick browse)",
            "detail": "Full activity details with computed duration",
        }

    def transform_hit(self, obj: Any, variant: str = "summary") -> dict[str, Any]:
        """Transform activity log for each variant."""
        now = timezone.now()
        activity_type = getattr(obj, 'action_type', 'unknown')
        timestamp = getattr(obj, 'timestamp', now)
        duration = now - timestamp

        # Format duration in human-readable way
        if duration.days > 0:
            duration_str = f"{duration.days} days ago"
        elif duration.seconds > 3600:
            duration_str = f"{duration.seconds // 3600} hours ago"
        elif duration.seconds > 60:
            duration_str = f"{duration.seconds // 60} minutes ago"
        else:
            duration_str = "Just now"

        if variant == "summary":
            # Quick summary
            user_name = getattr(obj.user, 'get_full_name', lambda: 'Unknown')()
            return {
                "display": f"{user_name} — {activity_type}",
                "subtitle": duration_str
            }

        else:  # detail
            # Full details
            user_name = getattr(obj.user, 'get_full_name', lambda: 'Unknown')()
            description = getattr(obj, 'description', '')
            return {
                "display": f"{user_name}: {activity_type}",
                "subtitle": description[:100] if description else "",
                "user": user_name,
                "action": activity_type,
                "duration_str": duration_str,
                "timestamp": timestamp.isoformat(),
                "hours_ago": int(duration.total_seconds() / 3600),
            }

    def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
        """Only index activities from the last 30 days."""
        cutoff = timezone.now() - timedelta(days=30)
        return qs.filter(timestamp__gte=cutoff)

    def get_ranking_weights(self) -> dict[str, int]:
        """Action type and user name are equally important."""
        return {
            "action_type": 2,
            "user__username": 2,
            "description": 1
        }


# ============================================================================
# Example 3: Help Article with Publication Status and Multi-Variant Output
# ============================================================================

class HelpArticleSearchBuilderExample:
    """SearchBuilder for help articles with published filter and multiple variants.

    Demonstrates:
    - Publication status filtering
    - Category/tag-based variant selection
    - Computed relevance score
    - Three variants for different use cases
    """

    def get_search_variants(self) -> dict[str, str]:
        """Three variants for different help contexts."""
        return {
            "search": "Article title + section (for search results)",
            "browse": "Extended summary for article browsing",
            "embed": "Lightweight for embedding in UI tooltips"
        }

    def transform_hit(self, obj: Any, variant: str = "search") -> dict[str, Any]:
        """Transform help article for each variant."""
        title = getattr(obj, 'title', 'Untitled')
        section = getattr(obj, 'section', 'General')
        content = getattr(obj, 'content', '')
        category = getattr(obj, 'category', 'Help')
        updated_at = getattr(obj, 'updated_at', None)

        base = {
            "id": obj.id,
            "display": title,
            "section": section,
        }

        if variant == "embed":
            # Ultra-lightweight for tooltips
            return {
                "display": f"{title} ({section})",
            }

        elif variant == "browse":
            # Extended browsing view
            base["subtitle"] = content[:150] + ("..." if len(content) > 150 else "")
            base["category"] = category
            base["updated_at"] = updated_at.isoformat() if updated_at else None
            base["content_length"] = len(content)
            return base

        else:  # search (default)
            # Standard search result
            base["subtitle"] = section
            base["content_preview"] = content[:80] + ("..." if len(content) > 80 else "")
            base["category"] = category
            return base

    def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
        """Only index published articles."""
        return qs.filter(published=True)

    def get_ranking_weights(self) -> dict[str, int]:
        """Title is most important, section helps distinguish."""
        return {
            "title": 3,
            "section": 2,
            "content": 1
        }


# ============================================================================
# Example 4: Ticket Search with Complex State-Based Ranking
# ============================================================================

class TicketSearchBuilderExample:
    """SearchBuilder for tickets with priority-based ranking and state indicators.

    Demonstrates:
    - Multiple computed fields (is_urgent, is_stale, days_open)
    - State-based visual indicators
    - Conditional field inclusion based on variant
    - Real-world filtering (archived exclusion)
    """

    def get_search_variants(self) -> dict[str, str]:
        """Variants for different ticket workflows."""
        return {
            "agent": "Structured for Claude agents (boolean flags, computed fields)",
            "list": "Compact list view with priority badge",
            "detail": "Full details with computed metrics"
        }

    def transform_hit(self, obj: Any, variant: str = "list") -> dict[str, Any]:
        """Transform ticket for each variant."""
        now = timezone.now()
        created_at = getattr(obj, 'created_at', now)
        days_open = (now - created_at).days if created_at else 0
        priority = getattr(obj, 'priority', 1)
        status = getattr(obj, 'status', 'open')

        # Computed fields
        is_urgent = priority >= 3
        is_stale = days_open > 7
        is_open = status in ['open', 'in_progress']

        base = {
            "id": obj.id,
            "display": getattr(obj, 'title', 'Untitled'),
        }

        if variant == "agent":
            # For Claude: structured booleans for decision-making
            base["priority"] = priority
            base["status"] = status
            base["is_urgent"] = is_urgent
            base["is_open"] = is_open
            base["is_stale"] = is_stale
            base["days_open"] = days_open
            # Additional computed
            base["needs_attention"] = is_open and (is_urgent or is_stale)
            return base

        elif variant == "detail":
            # Full display with all metrics
            priority_icon = "🔴" if is_urgent else "🟡"
            base["display"] = f"{priority_icon} {base['display']}"
            base["subtitle"] = getattr(obj, 'description', '')[:100]
            base["status"] = status
            base["priority"] = priority
            base["days_open"] = days_open
            base["customer"] = str(getattr(obj, 'customer', 'N/A'))
            return base

        else:  # list (default)
            # Quick list view with badge
            priority_icon = "🔴" if is_urgent else ("🟡" if priority == 2 else "🟢")
            base["display"] = f"{priority_icon} {base['display']}"
            base["subtitle"] = getattr(obj, 'customer', 'No customer')
            return base

    def filter_searchable_queryset(self, qs: QuerySet) -> QuerySet:
        """Exclude archived tickets."""
        return qs.filter(archived=False)

    def get_ranking_weights(self) -> dict[str, int]:
        """Title is primary, customer secondary."""
        return {
            "title": 3,
            "customer__name": 2,
            "description": 1
        }


# ============================================================================
# Example Usage Guide
# ============================================================================

"""
To use these examples in your SmallStack project:

1. **For User Search**:
   class MyUserCRUDView(CRUDView):
       model = User
       search_fields = ["username", "first_name", "last_name", "email"]
       enable_search = True
       # Add the SearchBuilder methods from UserSearchBuilderExample

       def get_search_variants(self):
           return UserSearchBuilderExample().get_search_variants()

       def transform_hit(self, obj, variant="admin"):
           return UserSearchBuilderExample().transform_hit(obj, variant)

       # ... etc for other methods

2. **For Activity Log Search**:
   Similar pattern with ActivityLogSearchBuilderExample

3. **For Help Article Search**:
   Similar pattern with HelpArticleSearchBuilderExample

4. **For Ticket Search**:
   Similar pattern with TicketSearchBuilderExample

Then rebuild the search index:
   $ python manage.py rebuild_search_index

And test in manage.py shell:
   >>> from apps.search.api import get_search_api
   >>> api = get_search_api()
   >>> results = api.search("app.Model", "query", variant="agent")
   >>> for hit in results:
   ...     print(hit.display, hit.extra)
"""
