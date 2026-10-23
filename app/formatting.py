"""Number and currency formatting shared by templates, CSV and messages.

The browser has an equivalent in static/app/js/format.js; keep them in sync.
"""
from decimal import ROUND_HALF_UP, Decimal

SEPARATORS = {
    "intl": (",", "."),
    "indian": (",", "."),
    "eu": (".", ","),
    "space": (" ", ","),
}


def _group(digits, indian):
    if len(digits) <= 3:
        return digits
    if not indian:
        parts = []
        while digits:
            parts.insert(0, digits[-3:])
            digits = digits[:-3]
        return parts
    head, tail = digits[:-3], digits[-3:]
    parts = [tail]
    while head:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return parts


def format_number(value, number_format="intl", places=2):
    value = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if value < 0 else ""
    text = f"{abs(value):.{places}f}"
    whole, _, frac = text.partition(".")
    group_sep, dec_sep = SEPARATORS.get(number_format, SEPARATORS["intl"])
    grouped = _group(whole, number_format == "indian")
    whole = group_sep.join(grouped) if isinstance(grouped, list) else grouped
    return f"{sign}{whole}{dec_sep}{frac}" if places else f"{sign}{whole}"


def format_money(value, profile=None, with_symbol=True):
    number_format = getattr(profile, "number_format", "intl")
    text = format_number(value, number_format)
    if not with_symbol:
        return text
    symbol = getattr(profile, "currency_symbol", "") or ""
    if not symbol:
        return text
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
    joiner = " " if symbol[-1].isalpha() else ""
    return f"{sign}{symbol}{joiner}{text}"
