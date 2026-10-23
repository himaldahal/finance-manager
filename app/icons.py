"""Icon names available in the sprite (Lucide, see app/static/app/icons/LICENSE)."""

UI_ICONS = (
    "layout-dashboard", "list", "tags", "target", "repeat", "chart-column", "upload", "download",
    "sliders-horizontal", "log-out", "plus", "menu", "x", "pencil", "trash-2", "pause", "play",
    "chevron-left", "chevron-right", "search", "eye", "eye-off", "bell", "flag", "arrow-left-right",
    "file-text", "check", "circle-alert", "bookmark", "copy", "triangle-alert", "trending-up",
    "clock", "printer", "users", "newspaper", "database", "copy", "history", "scissors", "lock", "rotate-ccw", "square-check", "panel-left-close", "panel-left-open", "chevron-down", "circle-check", "wand-sparkles",
)

CATEGORY_ICONS = (
    "tag", "shopping-cart", "utensils", "coffee", "house", "car", "bus", "fuel", "zap", "wifi",
    "smartphone", "heart-pulse", "pill", "graduation-cap", "plane", "gift", "shirt", "film",
    "music", "gamepad-2", "dumbbell", "baby", "paw-print", "briefcase", "banknote", "coins",
    "hand-coins", "piggy-bank", "wallet", "credit-card", "landmark", "receipt", "wrench",
    "shopping-bag", "book-open", "tv", "sparkles", "droplets", "building-2", "ellipsis",
)

ACCOUNT_ICONS = {"cash": "banknote", "bank": "landmark", "wallet": "wallet", "credit": "credit-card"}

ALL_ICONS = tuple(dict.fromkeys(UI_ICONS + CATEGORY_ICONS + tuple(ACCOUNT_ICONS.values()) + ("flag",)))
ICON_CHOICES = tuple((name, name.replace("-", " ").title()) for name in CATEGORY_ICONS)
