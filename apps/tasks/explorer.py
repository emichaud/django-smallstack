"""Explorer registration for background task results."""

from django.contrib import admin
from django_tasks_db.models import DBTaskResult

from apps.explorer.registry import explorer


class TaskResultExplorerAdmin(admin.ModelAdmin):
    list_display = ("task_path", "queue_name", "status", "enqueued_at", "finished_at")
    explorer_readonly = True
    explorer_paginate_by = 25


explorer.register(DBTaskResult, TaskResultExplorerAdmin, group="System")
