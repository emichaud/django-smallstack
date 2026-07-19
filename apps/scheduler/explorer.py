"""Explorer registration for raw scheduled-job-run browsing."""

from django.contrib import admin

from apps.explorer.registry import explorer

from .models import ScheduledJobRun


class ScheduledJobRunExplorerAdmin(admin.ModelAdmin):
    list_display = ("job", "status", "scheduled_for", "created_at", "task_result_id")
    explorer_readonly = True
    explorer_paginate_by = 25


explorer.register(ScheduledJobRun, ScheduledJobRunExplorerAdmin, group="System")
