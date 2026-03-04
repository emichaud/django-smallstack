---
title: Extending with AI
description: Using AI assistants to accelerate development
---

# Extending with AI

{{ project_name }} was jointly developed with the help of **Claude**, an AI assistant by Anthropic. This collaborative approach allowed for rapid iteration on features, documentation, and code quality.

If you plan to extend this starter project using AI coding assistants, you'll find that we've included resources specifically designed to help AI agents understand and work effectively with this codebase.

## AI-Assisted Development

Modern AI assistants like Claude, GitHub Copilot, and others can significantly accelerate Django development when given proper context about a project's structure and conventions.

### What AI Assistants Excel At

- **Generating boilerplate** - Models, views, forms, URL patterns
- **Writing templates** - HTML with proper Django template tags
- **Creating documentation** - Help pages, code comments, READMEs
- **Refactoring code** - Following established patterns consistently
- **Debugging** - Analyzing errors and suggesting fixes
- **Adding features** - Extending existing functionality

### Where Human Judgment Matters

- **Architecture decisions** - Overall system design
- **Security considerations** - Authentication, authorization, data protection
- **Business logic** - Domain-specific rules and requirements
- **User experience** - Design choices and workflows
- **Code review** - Verifying AI-generated code is correct

## Skill Files for AI Agents

We've included a set of **skill files** in `docs/skills/` that provide structured knowledge about this project. These files are designed to be read by AI assistants before they make changes to the codebase.

### Available Skills

| Skill | File | Use When... |
|-------|------|-------------|
| Django Apps | `django-apps.md` | Creating new Django applications |
| Templates | `templates.md` | Creating or modifying templates |
| Theming System | `theming-system.md` | Modifying CSS, colors, components |
| Authentication | `authentication.md` | Working with users and auth |
| Help Documentation | `help-documentation.md` | Adding or editing help pages |
| Logging & Audit | `logging-audit.md` | Adding logging or audit trails to new features |
| Kamal Deployment | `kamal-deployment.md` | Configuring or deploying with Kamal to a VPS |

### How to Use Skill Files

When working with an AI assistant, reference the relevant skill file before asking it to make changes:

**Example prompt:**
> "Read the file `docs/skills/django-apps.md` and then create a new app called `app_tasks` for managing user tasks. Follow the conventions described in the skill file."

**Example prompt:**
> "Review `docs/skills/help-documentation.md` and add a new help page about API integration. Make sure to update the `_config.yaml` with the correct icon and ordering."

### Why This Helps

AI assistants work better when they have:

1. **Clear conventions** - Knowing the project's naming patterns and structure
2. **File locations** - Understanding where different types of files belong
3. **Code examples** - Seeing how similar features are implemented
4. **Step-by-step procedures** - Following established workflows

The skill files provide all of this context in a format optimized for AI consumption.

## Tips for AI-Assisted Development

### Be Specific

Instead of:
> "Add a contact form"

Try:
> "Create a contact form in `smallstack` with fields for name, email, and message. Use the existing form styling patterns from `templates.md` skill file. Add a view that sends an email using Django's email backend."

### Provide Context

Instead of:
> "Fix the bug"

Try:
> "The profile photo isn't displaying on the edit page. The photo uploads correctly and shows on the profile view page. Check `apps/profile/views.py` and the template at `templates/profile/profile_edit.html`."

### Request Skill File Review

When starting a new feature:
> "Before we begin, read `docs/skills/django-apps.md` to understand the project conventions. Then let's plan a new app for [feature]."

### Verify Generated Code

Always review AI-generated code for:

- **Security issues** - SQL injection, XSS, CSRF protection
- **Logic errors** - Edge cases, error handling
- **Convention compliance** - Follows project patterns
- **Completeness** - Migrations, URL routing, admin registration

### Iterate Incrementally

Break large features into smaller tasks:

1. Create the model and migration
2. Add the admin interface
3. Create views and URLs
4. Build the templates
5. Add tests
6. Update documentation

This allows you to verify each step before proceeding.

## Example Workflow

Here's how you might use an AI assistant to add a new feature:

### 1. Planning

> "I want to add a notifications system to the app. Read `docs/skills/django-apps.md` and suggest how to structure this feature."

### 2. Implementation

> "Create the Notification model with fields for user, message, read status, and timestamp. Follow the model patterns from the skill file."

### 3. Views

> "Add views for listing notifications and marking them as read. Use LoginRequiredMixin as shown in the authentication skill file."

### 4. Templates

> "Create templates for the notification list. Extend base.html and use the card component pattern from `docs/skills/templates.md`."

### 5. Integration

> "Add a notification icon to the topbar that shows unread count. Reference `templates/smallstack/includes/topbar.html` for the existing pattern."

### 6. Documentation

> "Create a help page for the notifications feature. Follow the process in `docs/skills/help-documentation.md`."

## Contributing Skill Files

If you add significant new features or systems to the project, consider creating a corresponding skill file:

```
docs/skills/your-feature.md
```

Include:

- Overview of the system
- File locations
- Step-by-step procedures
- Code examples
- Configuration options
- Best practices

This helps future developers (and AI assistants) work effectively with your additions.

## The Human-AI Partnership

AI assistants are powerful tools for accelerating development, but they work best as collaborators rather than replacements for human judgment. Use them to:

- Handle repetitive coding tasks
- Generate initial implementations quickly
- Explore different approaches
- Document your work

While you focus on:

- Making architectural decisions
- Ensuring security and quality
- Understanding user needs
- Reviewing and refining the output

This partnership approach—human direction with AI acceleration—is how {{ project_name }} was built, and it's the workflow we recommend for extending it.
