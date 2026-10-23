"""Understand short natural phrases such as "food last month over 500" as transaction filters."""
import datetime
import re
from decimal import Decimal, InvalidOperation

from .services import add_months, month_end, month_start

MONTHS = {name: i + 1 for i, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"))}
MONTHS.update({name[:3]: i for name, i in list(MONTHS.items())})
STOP = {"the", "a", "an", "in", "on", "for", "my", "all", "of", "to", "and", "from", "show", "me", "what", "did", "i", "with"}
NUMBER = r"(\d[\d,]*(?:\.\d+)?)"


def _num(text):
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def parse(query, categories, accounts, tags, today):
    """Return (params, parts). ``params`` are TransactionFilter query parameters, ``parts`` describe them."""
    categories = sorted(categories, key=lambda c: len(c["name"]))  # prefer "Dining out" over "Dining out / Coffee"
    text = " " + " ".join(query.lower().split()) + " "
    params, parts = {}, []

    def take(pattern):
        nonlocal text
        m = re.search(pattern, text)
        if m:
            text = text[:m.start()] + " " + text[m.end():]
        return m

    # amounts
    m = take(r"\bbetween\s+" + NUMBER + r"\s+and\s+" + NUMBER)
    if m:
        lo, hi = sorted([_num(m.group(1)), _num(m.group(2))])
        params["min_amount"], params["max_amount"] = str(lo), str(hi)
        parts.append(f"between {lo} and {hi}")
    m = take(r"\b(?:over|above|more than|greater than|at least)\s+" + NUMBER)
    if m and _num(m.group(1)) is not None:
        params["min_amount"] = str(_num(m.group(1)))
        parts.append(f"over {m.group(1)}")
    m = take(r"\b(?:under|below|less than|at most)\s+" + NUMBER)
    if m and _num(m.group(1)) is not None:
        params["max_amount"] = str(_num(m.group(1)))
        parts.append(f"under {m.group(1)}")

    # dates
    this = month_start(today)
    ranges = (
        (r"\btoday\b", today, today, "today"),
        (r"\byesterday\b", today - datetime.timedelta(days=1), today - datetime.timedelta(days=1), "yesterday"),
        (r"\blast week\b", today - datetime.timedelta(days=today.weekday() + 7), today - datetime.timedelta(days=today.weekday() + 1), "last week"),
        (r"\bthis week\b", today - datetime.timedelta(days=today.weekday()), today, "this week"),
        (r"\blast month\b", add_months(this, -1), month_end(add_months(this, -1)), "last month"),
        (r"\bthis month\b", this, today, "this month"),
        (r"\blast year\b", datetime.date(today.year - 1, 1, 1), datetime.date(today.year - 1, 12, 31), "last year"),
        (r"\bthis year\b", datetime.date(today.year, 1, 1), today, "this year"),
    )
    for pattern, start, end, label in ranges:
        if take(pattern):
            params["date_from"], params["date_to"] = start.isoformat(), end.isoformat()
            parts.append(label)
            break
    else:
        m = take(r"\b(?:in\s+)?(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")(?:\s+(\d{4}))?\b")
        if m:
            year = int(m.group(2)) if m.group(2) else (today.year if MONTHS[m.group(1)] <= today.month else today.year - 1)
            first = datetime.date(year, MONTHS[m.group(1)], 1)
            params["date_from"], params["date_to"] = first.isoformat(), month_end(first).isoformat()
            parts.append(f"{first:%B %Y}")

    # type and notes
    if take(r"\b(?:income|earned|received|earnings)\b"):
        params["type"] = "income"
        parts.append("income")
    elif take(r"\b(?:expenses?|spent|spending|paid)\b"):
        params["type"] = "expense"
        parts.append("expenses")
    if take(r"\bwith notes?\b"):
        params["has_notes"] = "1"
        parts.append("with notes")

    # tags (#tag) , accounts, categories, then free text
    for tag in tags:
        if "tag" not in params and take(r"(?:^|\s)#" + re.escape(tag["name"].lower()) + r"(?=\s)"):
            params["tag"] = str(tag["id"])
            parts.append(f"tagged {tag['name']}")
    leftovers = [w for w in text.split() if w not in STOP]
    free = []
    for word in leftovers:
        cat = next((c for c in categories if c["name"].lower() == word or c["name"].lower().split(" / ")[-1] == word
                    or (len(word) >= 3 and c["name"].lower().startswith(word))), None)
        acct = next((a for a in accounts if a["name"].lower() == word), None)
        if cat and "category" not in params:
            params["category"] = str(cat["id"])
            parts.append(cat["name"])
        elif acct and "account" not in params:
            params["account"] = str(acct["id"])
            parts.append(acct["name"])
        else:
            free.append(word)
    if free:
        params["q"] = " ".join(free)
        parts.append(f"matching “{params['q']}”")
    return params, parts

