from django.urls import path

from .registry import explorer_registry
from .views import ExplorerIndexView

urlpatterns = [
    path("explorer/", ExplorerIndexView.as_view(), name="explorer-index"),
    *explorer_registry.get_url_patterns(),
]
