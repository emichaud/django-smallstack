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
    path("getting-started/", views.getting_started_view, name="getting_started"),
    path("starter/", views.starter_view, name="starter"),
    path("starter/basic/", views.starter_basic_view, name="starter_basic"),
    path("starter/forms/", views.starter_forms_view, name="starter_forms"),
    path("components/", views.components_view, name="components"),
]
