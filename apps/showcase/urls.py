"""Showcase URL patterns: SmallStack's demo pages, mounted at the site root."""

from django.urls import path

from . import views

app_name = "showcase"

urlpatterns = [
    path("about/", views.about_view, name="about"),
    path("getting-started/", views.getting_started_view, name="getting_started"),
    path("prompts/", views.prompts_view, name="prompts"),
    path("faq/", views.faq_view, name="faq"),
    path("platform/datasets-calendars/", views.platform_datasets_calendars_view, name="platform_datasets_calendars"),
    path("platform/blogs-newsletters/", views.platform_blogs_newsletters_view, name="platform_blogs_newsletters"),
    path("starter/", views.starter_view, name="starter"),
    path("starter/basic/", views.starter_basic_view, name="starter_basic"),
    path("starter/forms/", views.starter_forms_view, name="starter_forms"),
    path("starter/dashboard/", views.starter_dashboard_view, name="starter_dashboard"),
    path("starter/own-theme/", views.starter_own_theme_view, name="starter_own_theme"),
    path("components/", views.components_view, name="components"),
    path("search/", views.search_view, name="search"),
]
