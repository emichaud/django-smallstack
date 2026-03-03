"""
Website URL patterns - customize for your project.

Add your project-specific page routes here. This keeps them
separate from SmallStack core URLs, avoiding merge conflicts
when pulling upstream updates.
"""

from django.urls import path

from . import views

app_name = "website"

urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.about_view, name="about"),
]
