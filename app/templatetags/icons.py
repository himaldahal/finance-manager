from django import template
from django.templatetags.static import static
from django.utils.html import format_html

from ..icons import ALL_ICONS

register = template.Library()
KNOWN = set(ALL_ICONS)


@register.simple_tag
def icon(name, css_class=""):
    """Inline reference to a symbol in the self-hosted Lucide sprite."""
    if name not in KNOWN:
        return ""
    return format_html(
        '<svg class="icon{}" aria-hidden="true" focusable="false"><use href="{}#{}"/></svg>',
        f" {css_class}" if css_class else "", static("app/icons/sprite.svg"), name,
    )
