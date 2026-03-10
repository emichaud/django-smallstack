# Teams & Organizations — v1.0 Requirement

SmallStack's sweet spot is internal business tools. Internal tools almost always need
users grouped by team or organization — for scoping data, filtering dashboards,
assigning work, and managing permissions. This should ship in 1.0.

## Goals

- Simple team/org model that covers 80% of internal tool needs
- Users belong to one or more teams (M2M relationship)
- Team-aware context available in views and templates
- Works with existing auth, profiles, and activity tracking
- Not full multi-tenancy — data is shared, access is scoped

## Data Model

### Core Models

```python
# apps/teams/models.py

class Organization(models.Model):
    """Top-level org. Many apps only need one, but the model supports multiple."""
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Team(models.Model):
    """A team within an organization."""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=200)
    slug = models.SlugField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["organization", "slug"]

class Membership(models.Model):
    """User's membership in a team with a role."""
    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        ADMIN = "admin", "Admin"
        OWNER = "owner", "Owner"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "team"]
```

### Key Relationships

- User → many Teams (through Membership)
- Team → one Organization
- Membership carries a role (member/admin/owner)

## Integration Points

### 1. User Profile

- Add `current_team` or `current_org` to UserProfile (optional, for team-switching UIs)
- Or derive from middleware/context processor

### 2. Context Processor

```python
# apps/teams/context_processors.py
def team_context(request):
    """Make current user's teams available in templates."""
    if request.user.is_authenticated:
        return {
            "user_teams": request.user.memberships.select_related("team", "team__organization").all(),
        }
    return {}
```

### 3. Activity Tracking

- Optionally tag activity records with team/org
- Filter activity dashboard by team
- "What's my team been doing?" is a common internal tool question

### 4. Mixins for Views

```python
# apps/teams/mixins.py
class TeamRequiredMixin:
    """Ensure user belongs to at least one team."""
    pass

class TeamScopedMixin:
    """Filter queryset to current team's data."""
    pass
```

### 5. Admin Integration

- Register Team, Organization, Membership in Django Admin
- Inline memberships on the User admin page
- Team filter on relevant admin list views

### 6. Template Tags

```python
# {% load team_tags %}
# {% if user|is_team_admin:team %}...{% endif %}
# {% user_teams as teams %}
```

## What Ships

- `apps/teams/` app with models, admin, context processor, mixins, template tags
- Management command to create initial org/team (`create_default_org`)
- Example team-scoped view pattern in docs
- Migration that plays nice with existing User model

## What Doesn't Ship (v1.0)

- Team switching UI (users can be on multiple teams, but no switcher widget yet)
- Invitation system (add users via admin or management command)
- Team-level permissions (use Django's groups for now, team-aware perms later)
- Per-team settings or configuration
- API endpoints for team management

## Settings

```python
# config/settings/base.py
TEAMS_ENABLED = True                    # Toggle the teams feature
TEAMS_DEFAULT_ORG_NAME = "My Company"   # Name for the auto-created org
TEAMS_REQUIRE_MEMBERSHIP = False        # If True, users must belong to a team
```

## Questions to Resolve

1. **Single org vs. multi-org:** Most internal tools have one org with multiple teams. Should the Organization model exist at all in v1, or just have Teams directly? Simpler to skip Org and add it later, but the M2M through Membership is the same either way.
2. **Auto-assign on signup:** Should new users automatically join a default team, or require manual assignment? For internal tools, auto-assign makes sense (everyone's on the same team initially).
3. **Team-scoped data pattern:** Provide a concrete mixin that filters querysets by team, or just document the pattern? Mixin is more useful but couples the teams app to how downstream apps structure their models.
4. **Relationship to User Manager (v1.0):** The User Manager feature should be team-aware — manage users within a team context. These two features should be designed together.
