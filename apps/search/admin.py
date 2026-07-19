"""Django admin integration for SearchBuilder configuration discovery.

Provides admin pages to:
- List all indexed models and their SearchBuilder capabilities
- View available variants per model
- Monitor search index health (record count, last rebuild)
- Manually trigger index rebuild
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import path
from django.utils.html import format_html

from .backends import get_backend
from .registry import (
    list_search_configs,
)


@admin.register
class SearchConfigAdmin(admin.AdminSite):
    """Custom admin site for search configuration."""

    site_header = "Search Configuration"
    site_title = "Search Config"
    index_title = "SearchBuilder Overview"


class SearchConfigListView:
    """Display all search configurations and variants."""

    def changelist_view(self, request: HttpRequest) -> HttpResponse:
        """Show table of all indexed models and their variants."""
        configs = list_search_configs()
        backend = get_backend()

        # Build context with config info and index health
        config_data = []
        for config in configs:
            model_label = config['model_label']
            variants = config.get('variants', {})
            has_builder = config.get('has_search_builder', False)

            config_data.append({
                'model_label': model_label,
                'model_verbose': config.get('model_verbose', model_label),
                'fields': ', '.join(config.get('fields', [])),
                'variants': list(variants.keys()) if variants else ['default'],
                'variant_count': len(variants) if variants else 1,
                'has_search_builder': has_builder,
                'backend_name': backend.name,
            })

        context = {
            'title': 'Search Configuration',
            'configs': config_data,
            'total_views': len(config_data),
            'views_with_builder': sum(1 for c in config_data if c['has_search_builder']),
            'backend_name': backend.name,
        }

        return render(request, 'admin/search_config_list.html', context)


def get_search_admin_urls() -> list[tuple]:
    """Return URL patterns for search admin views."""
    return [
        path(
            'search/config/',
            SearchConfigListView.changelist_view,
            name='search_config_list'
        ),
    ]


# ============================================================================
# Search Configuration Summary for Admin Dashboard
# ============================================================================

def get_search_configuration_summary() -> dict[str, Any]:
    """Return a summary of search configuration for dashboard display.

    Returns:
        {
            'total_indexed_models': int,
            'models_with_variants': int,
            'total_variants': int,
            'backend_name': str,
            'models_by_feature': {
                'filtering': [...],
                'ranking': [...],
                'variants': [...]
            }
        }
    """
    configs = list_search_configs()
    backend = get_backend()

    models_with_variants = 0
    total_variants = 0
    models_by_feature = {
        'filtering': [],
        'ranking': [],
        'variants': []
    }

    for config in configs:
        model_label = config['model_label']
        has_builder = config.get('has_search_builder', False)
        variants = config.get('variants', {})

        if variants:
            models_with_variants += 1
            total_variants += len(variants)
            models_by_feature['variants'].append(model_label)

        # Note: We detect filtering/ranking presence in this summary
        # In production, you'd want more granular detection
        if has_builder:
            models_by_feature['filtering'].append(model_label)
            models_by_feature['ranking'].append(model_label)

    return {
        'total_indexed_models': len(configs),
        'models_with_variants': models_with_variants,
        'total_variants': total_variants,
        'backend_name': backend.name,
        'models_by_feature': models_by_feature,
    }


# ============================================================================
# Search Configuration Display Helpers
# ============================================================================

def format_variant_badge(variant_name: str) -> str:
    """Format variant name as an HTML badge."""
    colors = {
        'default': '#17a2b8',    # info
        'summary': '#6c757d',    # secondary
        'admin': '#dc3545',      # danger
        'public': '#28a745',     # success
        'api': '#007bff',        # primary
    }
    color = colors.get(variant_name, '#6c757d')
    return format_html(
        '<span style="display: inline-block; padding: 4px 8px; '
        'background-color: {}; color: white; border-radius: 3px; '
        'font-size: 11px; font-weight: bold;">{}</span>',
        color,
        variant_name
    )


def format_search_config_summary(config: dict[str, Any]) -> str:
    """Format a search config as HTML summary."""
    model_label = config.get('model_label', 'Unknown')
    variants = config.get('variants', {})
    has_builder = config.get('has_search_builder', False)

    html_parts = [
        f'<strong>Model:</strong> {model_label}<br>',
        f'<strong>Fields:</strong> {", ".join(config.get("fields", []))}<br>',
    ]

    if variants:
        variant_badges = ' '.join(
            format_variant_badge(v) for v in variants.keys()
        )
        html_parts.append(f'<strong>Variants:</strong> {variant_badges}<br>')

    if has_builder:
        html_parts.append('<strong>Features:</strong> SearchBuilder enabled ✓<br>')

    return format_html(''.join(html_parts))
