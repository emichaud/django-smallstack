"""Seed the Runbook app with sample data."""

from typing import Any

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand

from apps.runbook.models import Document, Runbook, Section

User = get_user_model()

SAMPLE_SLIDES_MD = """---
title: Deploy Checklist
---

# Deploy Checklist

A quick guide to deploying safely.

---

# Pre-Deploy

- Run tests locally
- Check CI/CD pipeline is green
- Review open PRs
- Verify staging environment

---

# Deploy Steps

1. Merge to main
2. Monitor CI build
3. Verify deployment health check
4. Check error rates

---

# Post-Deploy

- Verify key user flows
- Check monitoring dashboards
- Announce in team channel
- Update changelog
"""

SAMPLE_STEPS_MD = """---
title: New Hire Onboarding
---

# New Hire Onboarding Process

Follow these steps for each new team member.

## Step 1: Account Setup

Create accounts in the following systems:
- Email (Google Workspace)
- Slack
- GitHub (add to team)
- VPN credentials

> note: HR must approve account creation before proceeding.

## Step 2: Hardware Provisioning

- Assign laptop from inventory
- Configure with standard image
- Install required software (IDE, Docker, etc.)

> note: Allow 2-3 business days for hardware prep.

## Step 3: Team Introduction

- Schedule 1:1 with manager
- Add to team standup calendar
- Assign onboarding buddy
- Share team wiki and documentation

## Step 4: First Week Tasks

- Complete security training
- Set up local development environment
- Review architecture documentation
- Submit first PR (onboarding task)

> note: The onboarding buddy should pair-program on the first PR.
"""

SAMPLE_ARCHITECTURE_MD = """---
title: System Architecture
---

# System Architecture Overview

## Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Web App | Django 6.0 | Main application server |
| Database | PostgreSQL 16 | Primary data store |
| Cache | Redis 7 | Session cache, task queue |
| Worker | django-tasks | Background job processing |

## Deployment

The application is deployed using Kamal to a VPS.
Docker containers are managed automatically.

## Data Flow

1. User request hits nginx reverse proxy
2. Nginx routes to Django via gunicorn
3. Django processes request, queries PostgreSQL
4. Response rendered and returned

## Monitoring

- Health check endpoint: `/health/`
- Status page: `/status/`
- Logs: `kamal app logs`
"""


class Command(BaseCommand):
    help = "Seed the Runbook app with sample sections and documents."

    def handle(self, *args: Any, **options: Any) -> None:
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            self.stderr.write("No superuser found. Run `make setup` first.")
            return

        # Create a default runbook
        runbook, rb_created = Runbook.objects.get_or_create(
            slug="default-runbook",
            defaults={"name": "Default Runbook", "description": "Sample runbook with seed data."},
        )
        status = "Created" if rb_created else "Exists"
        self.stdout.write(f"  {status}: Runbook '{runbook.name}'")

        # Create sections
        sections_data = [
            ("Onboarding", "onboarding", "New hire onboarding procedures", 0),
            ("Operations", "operations", "Day-to-day operational guides", 1),
            ("Incident Response", "incident-response", "How to handle production incidents", 2),
            ("Architecture", "architecture", "System architecture and design docs", 3),
        ]

        sections = {}
        for name, slug, desc, order in sections_data:
            section, created = Section.objects.get_or_create(
                slug=slug,
                runbook=runbook,
                defaults={"name": name, "description": desc, "order": order},
            )
            sections[slug] = section
            status = "Created" if created else "Exists"
            self.stdout.write(f"  {status}: Section '{name}'")

        # Create sample documents
        docs_data = [
            ("Deploy Checklist", sections["operations"], SAMPLE_SLIDES_MD, "deploy-checklist.md"),
            ("New Hire Onboarding", sections["onboarding"], SAMPLE_STEPS_MD, "new-hire-onboarding.md"),
            ("System Architecture", sections["architecture"], SAMPLE_ARCHITECTURE_MD, "system-architecture.md"),
        ]

        from django.utils.text import slugify

        for title, section, content, filename in docs_data:
            if not Document.objects.filter(title=title, is_archived=False).exists():
                doc = Document(
                    title=title,
                    runbook=section.runbook,
                    section=section,
                    key=slugify(title),
                    description=f"Sample {title.lower()} document",
                    created_by=user,
                    via="web",
                )
                doc.save()
                doc.create_new_version(
                    file=SimpleUploadedFile(filename, content.encode("utf-8")),
                    created_by=user,
                    via="web",
                )
                self.stdout.write(f"  Created: Document '{title}'")
            else:
                self.stdout.write(f"  Exists: Document '{title}'")

        # Create a multi-version document
        base_title = "Deploy Checklist"
        base_doc = Document.objects.filter(title=base_title, is_archived=False).first()
        if base_doc and base_doc.version == 1:
            v2_content = SAMPLE_SLIDES_MD.replace("A quick guide", "An updated guide (v2)")
            base_doc.create_new_version(
                file=SimpleUploadedFile("deploy-checklist-v2.md", v2_content.encode("utf-8")),
                created_by=user,
                description="Updated with post-deploy monitoring steps",
                via="web",
            )
            self.stdout.write(f"  Created: Document '{base_title}' v2 (version chain)")

        self.stdout.write(self.style.SUCCESS("\nRunbook seed data created successfully."))
