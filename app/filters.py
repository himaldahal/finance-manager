"""Query-string driven filtering, sorting and pagination of transactions."""
import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.db.models import Q

from .models import MAX_AMOUNT, Transaction

PAGE_SIZES = (10, 25, 50, 100)
DEFAULT_PAGE_SIZE = 25
SORT_FIELDS = {
    "date": "date",
    "amount": "amount",
    "name": "name",
    "category": "category__name",
}
DEFAULT_SORT = "-date"
SORT_OPTIONS = (
    ("-date", "Newest first"), ("date", "Oldest first"), ("-amount", "Largest first"), ("amount", "Smallest first"),
    ("name", "Description A-Z"), ("category", "Category A-Z"),
)


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _decimal(value):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number < 0 or number > MAX_AMOUNT:
        return None
    return number


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class TransactionFilter:
    """Parses request.GET leniently: invalid values are ignored."""

    def __init__(self, user, params):
        self.user = user
        get = params.get
        self.q = (get("q") or "").strip()[:100]
        kind = get("type")
        self.kind = kind if kind in ("income", "expense") else ""
        self.category = _int(get("category"))
        self.tag = _int(get("tag"))
        self.account = _int(get("account"))
        self.payee = (get("payee") or "").strip()[:80]
        self.has_notes = get("has_notes") == "1"
        self.date_from = _date(get("date_from"))
        self.date_to = _date(get("date_to"))
        self.min_amount = _decimal(get("min_amount"))
        self.max_amount = _decimal(get("max_amount"))
        sort = get("sort") or DEFAULT_SORT
        self.sort = sort if sort.lstrip("-") in SORT_FIELDS else DEFAULT_SORT
        size = _int(get("page_size"), DEFAULT_PAGE_SIZE)
        self.page_size = size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
        self.page = max(_int(get("page"), 1), 1)

    def queryset(self):
        qs = Transaction.objects.filter(user=self.user).select_related("category", "account").prefetch_related("tags")
        if self.q:
            qs = qs.filter(Q(name__icontains=self.q) | Q(note__icontains=self.q)
                           | Q(payee__icontains=self.q) | Q(category__name__icontains=self.q))
        if self.kind:
            qs = qs.filter(kind=self.kind)
        if self.category:
            qs = qs.filter(category_id=self.category)
        if self.tag:
            qs = qs.filter(tags__id=self.tag, tags__user=self.user)
        if self.account:
            qs = qs.filter(account_id=self.account)
        if self.payee:
            qs = qs.filter(payee__iexact=self.payee)
        if self.has_notes:
            qs = qs.exclude(note="")
        if self.date_from:
            qs = qs.filter(date__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(date__lte=self.date_to)
        if self.min_amount is not None:
            qs = qs.filter(amount__gte=self.min_amount)
        if self.max_amount is not None:
            qs = qs.filter(amount__lte=self.max_amount)
        descending = self.sort.startswith("-")
        field = SORT_FIELDS[self.sort.lstrip("-")]
        order = f"-{field}" if descending else field
        return qs.order_by(order, "-id" if descending else "id")

    def params(self, **overrides):
        """Non-default parameters as a dict, with overrides applied (None removes)."""
        data = {
            "q": self.q,
            "type": self.kind,
            "category": self.category or "",
            "tag": self.tag or "",
            "account": self.account or "",
            "payee": self.payee,
            "has_notes": "1" if self.has_notes else "",
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
            "min_amount": self.min_amount if self.min_amount is not None else "",
            "max_amount": self.max_amount if self.max_amount is not None else "",
            "sort": self.sort if self.sort != DEFAULT_SORT else "",
            "page_size": self.page_size if self.page_size != DEFAULT_PAGE_SIZE else "",
            "page": self.page if self.page > 1 else "",
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v not in ("", None)}

    def query_string(self, **overrides):
        return urlencode(self.params(**overrides))

    @property
    def active(self):
        return bool(self.q or self.kind or self.category or self.tag or self.account or self.payee or self.has_notes or self.date_from or self.date_to
                    or self.min_amount is not None or self.max_amount is not None)

    def sort_header(self, key, label, numeric=False):
        current = self.sort.lstrip("-")
        descending = self.sort.startswith("-")
        if current == key:
            nxt = key if descending else f"-{key}"
            state = "descending" if descending else "ascending"
        else:
            nxt = f"-{key}" if key in ("date", "amount") else key
            state = "none"
        return {
            "label": label, "numeric": numeric, "aria": state,
            "indicator": {"ascending": "\u25b2", "descending": "\u25bc"}.get(state, ""),
            "href": "?" + self.query_string(sort=nxt, page=""),
        }

    def page_href(self, number):
        return "?" + self.query_string(page=number if number > 1 else "")
