from django.urls import path

from .registry import explorer
from .views import (
    ExplorerAppPageView,
    ExplorerClassicIndexView,
    ExplorerGroupPageView,
    ExplorerHeartbeatPageView,
    ExplorerIndexView,
    ExplorerSingleModelPageView,
)

urlpatterns = [
    path("explorer/", ExplorerIndexView.as_view(), name="explorer-index"),
    # Composability examples
    path(
        "explorer/examples/classic/",
        ExplorerClassicIndexView.as_view(),
        name="explorer-example-classic",
    ),
    path(
        "explorer/examples/group/<str:group>/",
        ExplorerGroupPageView.as_view(),
        name="explorer-example-group",
    ),
    path(
        "explorer/examples/app/<str:app_label>/",
        ExplorerAppPageView.as_view(),
        name="explorer-example-app",
    ),
    path(
        "explorer/examples/model/<str:app_label>/<str:model_name>/",
        ExplorerSingleModelPageView.as_view(),
        name="explorer-example-model",
    ),
    path(
        "explorer/examples/heartbeat/",
        ExplorerHeartbeatPageView.as_view(),
        name="explorer-example-heartbeat",
    ),
    *explorer.get_url_patterns(),
]
