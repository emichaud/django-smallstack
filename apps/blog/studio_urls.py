"""The writing studio — mounted at ``/my/blogs/`` in config/urls.py.

Namespaced ``myblogs`` so nothing here can collide with the console's bare
CRUDView names or the public ``blog:`` namespace. Everything is login-gated
in the views; there is no anonymous route in this module.
"""

from __future__ import annotations

from django.urls import path

from . import studio_views as views

app_name = "myblogs"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("new/", views.blog_new, name="blog_new"),
    path("<slug:blog_slug>/", views.blog_detail, name="blog_detail"),
    path("<slug:blog_slug>/settings/", views.blog_settings, name="blog_settings"),
    path("<slug:blog_slug>/posts/new/", views.post_new, name="post_new"),
    path("<slug:blog_slug>/posts/<int:pk>/", views.post_edit, name="post_edit"),
    path("<slug:blog_slug>/posts/<int:pk>/delete/", views.post_delete, name="post_delete"),
]
