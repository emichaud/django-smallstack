"""Explorer registration for background task results."""

from django.contrib import admin

from apps.explorer.registry import explorer
from django_tasks_db.models import DBTaskResult


class TaskResultExplorerAdmin(admin.ModelAdmin):
    list_display = ("task_path", "queue_name", "status", "enqueued_at", "finished_at")
    explorer_readonly = True
    explorer_paginate_by = 25


explorer.register(DBTaskResult, TaskResultExplorerAdmin, group="System")
