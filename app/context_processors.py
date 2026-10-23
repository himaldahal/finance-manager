from django.templatetags.static import static

from . import services


def shell(request):
    """Values every signed-in page needs: currency settings, category and account choices."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated or request.path.startswith("/admin/"):
        return {}
    profile = services.get_profile(user)
    categories = list(user.categories.select_related("parent"))
    return {
        "profile": profile,
        "shell_categories": [
            {"id": c.id, "name": c.name, "full_name": c.full_name, "kind": c.kind, "color": c.color, "icon": c.icon,
             "parent": c.parent_id} for c in sorted(categories, key=lambda c: c.full_name.lower())
        ],
        "shell_accounts": list(user.accounts.filter(archived=False).values("id", "name", "type")),
        "money_config": {
            "symbol": profile.currency_symbol,
            "code": profile.currency_code,
            "format": profile.number_format,
        },
        "sprite_url": static("app/icons/sprite.svg"),
        "nav": getattr(request.resolver_match, "url_name", ""),
    }
