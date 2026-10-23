"""Full-data JSON backup: export, strict validation, and restore (replaces the user's data)."""
import datetime
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from . import services
from .icons import CATEGORY_ICONS
from .models import (
    ACCOUNT_TYPES, CATEGORY_KIND_CHOICES, COLOR_CHOICES, LEDGER_KINDS, MAX_AMOUNT, MIN_DATE, NUMBER_FORMATS, Account, AuditEntry,
    Budget, Category, CategoryRule, Contribution, Goal, LedgerEntry, MonthLock, Person, Profile, RecurringTransaction, SavedView,
    Tag, Transaction, Transfer,
)

FORMAT = "finance-manager-backup"
VERSION = 1
MAX_BYTES = 8 * 1024 * 1024


class BackupError(Exception):
    def __init__(self, problems):
        self.problems = problems if isinstance(problems, list) else [problems]
        super().__init__("; ".join(self.problems[:5]))


def _d(value):
    return None if value is None else f"{value:.2f}"


def export_data(user):
    profile = services.get_profile(user)
    cats = list(Category.objects.filter(user=user).select_related("parent"))
    txs = (Transaction.objects.filter(user=user).select_related("category", "account").prefetch_related("tags")
           .order_by("date", "id"))
    return {
        "format": FORMAT, "version": VERSION, "exported_at": timezone.now().isoformat(),
        "profile": {
            "currency_code": profile.currency_code, "currency_symbol": profile.currency_symbol,
            "number_format": profile.number_format, "allow_negative_balance": profile.allow_negative_balance,
            "secondary_currency_code": profile.secondary_currency_code,
            "secondary_rate": str(profile.secondary_rate) if profile.secondary_rate is not None else None,
        },
        "accounts": [{"name": a.name, "type": a.type, "opening_balance": _d(a.opening_balance), "archived": a.archived}
                     for a in Account.objects.filter(user=user)],
        "categories": [{"name": c.name, "kind": c.kind, "color": c.color, "icon": c.icon,
                        "parent": c.parent.name if c.parent_id else None} for c in cats],
        "tags": [t.name for t in Tag.objects.filter(user=user)],
        "rules": [{"pattern": r.pattern, "category": r.category.name, "priority": r.priority, "active": r.active}
                  for r in CategoryRule.objects.filter(user=user).select_related("category")],
        "transactions": [{
            "name": t.name, "amount": _d(t.amount), "date": t.date.isoformat(), "kind": t.kind, "category": t.category.name,
            "account": t.account.name if t.account_id else None, "payee": t.payee, "note": t.note,
            "tags": [x.name for x in t.tags.all()], "split_group": str(t.split_group) if t.split_group else None,
            "reconciled": t.reconciled} for t in txs],
        "transfers": [{"from": t.from_account.name, "to": t.to_account.name, "amount": _d(t.amount), "date": t.date.isoformat(),
                       "note": t.note} for t in Transfer.objects.filter(user=user).select_related("from_account", "to_account")],
        "budgets": [{"category": b.category.name if b.category_id else None, "month": b.month.strftime("%Y-%m"),
                     "amount": _d(b.amount), "rollover": b.rollover, "warn_percent": b.warn_percent}
                    for b in Budget.objects.filter(user=user).select_related("category")],
        "goals": [{"name": g.name, "target_amount": _d(g.target_amount),
                   "target_date": g.target_date.isoformat() if g.target_date else None,
                   "account": g.account.name if g.account_id else None, "category": g.category.name if g.category_id else None,
                   "contributions": [{"amount": _d(c.amount), "date": c.date.isoformat(), "note": c.note}
                                     for c in g.contributions.all()]}
                  for g in Goal.objects.filter(user=user).select_related("account", "category").prefetch_related("contributions")],
        "recurring": [{"name": r.name, "amount": _d(r.amount), "kind": r.kind, "category": r.category.name, "payee": r.payee,
                       "account": r.account.name if r.account_id else None, "note": r.note, "frequency": r.frequency,
                       "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat() if r.end_date else None,
                       "next_due": r.next_due.isoformat(), "active": r.active}
                      for r in RecurringTransaction.objects.filter(user=user).select_related("category", "account")],
        "views": [{"name": v.name, "query": v.query} for v in SavedView.objects.filter(user=user)],
        "locked_months": [m.month.strftime("%Y-%m") for m in MonthLock.objects.filter(user=user)],
        "people": [{"name": p.name, "entries": [{"kind": e.kind, "amount": _d(e.amount), "description": e.description,
                                                "date": e.date.isoformat(), "due_date": e.due_date.isoformat() if e.due_date else None}
                                               for e in p.entries.all()]} for p in Person.objects.filter(user=user)],
    }


def dumps(user):
    return json.dumps(export_data(user), indent=2, ensure_ascii=False)


# --- validation ---------------------------------------------------------------

class _Checker:
    def __init__(self):
        self.problems = []

    def bad(self, where, text):
        if len(self.problems) < 25:
            self.problems.append(f"{where}: {text}")

    def text(self, row, key, where, maximum, required=True, default=""):
        value = row.get(key, default)
        if value is None and not required:
            return ""
        if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
            self.bad(where, f"{key} must be text of 1 to {maximum} characters" if required else f"{key} is too long")
            return default
        return value

    def money(self, row, key, where, positive=True, signed=False):
        try:
            value = Decimal(str(row.get(key)))
            if not value.is_finite() or abs(value) > MAX_AMOUNT * 10 or value != value.quantize(Decimal("0.01")):
                raise InvalidOperation
            if positive and value <= 0:
                raise InvalidOperation
            if not signed and not positive and value < 0:
                raise InvalidOperation
            return value
        except (InvalidOperation, ValueError, TypeError):
            self.bad(where, f"{key} is not a valid amount")
            return Decimal("1.00")

    def date(self, row, key, where, required=True):
        value = row.get(key)
        if value in (None, "") and not required:
            return None
        try:
            parsed = datetime.date.fromisoformat(value)
            if parsed < MIN_DATE or parsed > timezone.localdate() + datetime.timedelta(days=3660):
                raise ValueError
            return parsed
        except (ValueError, TypeError):
            self.bad(where, f"{key} must be a date like 2025-03-31")
            return MIN_DATE

    def choice(self, row, key, where, choices):
        value = row.get(key)
        if value not in {c[0] for c in choices}:
            self.bad(where, f"{key} must be one of {', '.join(c[0] for c in choices)}")
        return value

    def month(self, value, where):
        try:
            parsed = datetime.date.fromisoformat(f"{value}-01")
            if parsed < MIN_DATE:
                raise ValueError
            return parsed
        except (ValueError, TypeError):
            self.bad(where, "month must look like 2025-03")
            return MIN_DATE


def parse(raw):
    """Decode and validate a backup. Returns a dict ready for :func:`restore`; raises BackupError."""
    if len(raw) > MAX_BYTES:
        raise BackupError("The file is too large (limit 8 MB).")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise BackupError("This is not a valid JSON file.") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("This file is not a Finance Manager backup.")
    if data.get("version") != VERSION:
        raise BackupError(f"Unsupported backup version {data.get('version')!r}; this app reads version {VERSION}.")
    c = _Checker()

    def rows(key):
        value = data.get(key, [])
        if not isinstance(value, list) or len(value) > 200000:
            c.bad(key, "must be a list")
            return []
        out = []
        for i, row in enumerate(value):
            if isinstance(row, dict):
                out.append((f"{key}[{i}]", row))
            else:
                c.bad(f"{key}[{i}]", "must be an object")
        return out

    out = {"profile": data.get("profile") if isinstance(data.get("profile"), dict) else {}}
    p = out["profile"]
    if p:
        c.text(p, "currency_code", "profile", 3)
        c.text(p, "currency_symbol", "profile", 5)
        if p.get("number_format") not in {n[0] for n in NUMBER_FORMATS}:
            c.bad("profile", "number_format is not recognised")

    accounts = []
    for where, r in rows("accounts"):
        accounts.append({"name": c.text(r, "name", where, 60), "type": c.choice(r, "type", where, ACCOUNT_TYPES),
                         "opening_balance": c.money(r, "opening_balance", where, positive=False, signed=True),
                         "archived": bool(r.get("archived", False))})
    names = [a["name"].lower() for a in accounts]
    if len(set(names)) != len(names):
        c.bad("accounts", "account names must be unique")
    out["accounts"] = accounts
    acct_names = set(names)

    categories = []
    for where, r in rows("categories"):
        icon = r.get("icon", "tag")
        categories.append({"name": c.text(r, "name", where, 50), "kind": c.choice(r, "kind", where, CATEGORY_KIND_CHOICES),
                           "color": c.choice(r, "color", where, COLOR_CHOICES), "icon": icon if icon in CATEGORY_ICONS else "tag",
                           "parent": r.get("parent")})
    cat_names = [x["name"].lower() for x in categories]
    if len(set(cat_names)) != len(cat_names):
        c.bad("categories", "category names must be unique")
    for x in categories:
        if x["parent"] is not None and (not isinstance(x["parent"], str) or x["parent"].lower() not in cat_names):
            c.bad("categories", f"parent of {x['name']!r} does not exist")
    out["categories"] = categories
    cat_set = set(cat_names)

    def cat_ref(r, key, where, required=True):
        value = r.get(key)
        if value is None and not required:
            return None
        if not isinstance(value, str) or value.lower() not in cat_set:
            c.bad(where, f"unknown category {value!r}")
        return value

    def acct_ref(r, key, where):
        value = r.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or value.lower() not in acct_names:
            c.bad(where, f"unknown account {value!r}")
        return value

    tags = data.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() or len(t) > 30 for t in tags):
        c.bad("tags", "must be a list of names up to 30 characters")
        tags = []
    out["tags"] = tags

    out["rules"] = [{"pattern": c.text(r, "pattern", w, 60), "category": cat_ref(r, "category", w),
                     "priority": int(r.get("priority", 100)) if isinstance(r.get("priority", 100), int) else 100,
                     "active": bool(r.get("active", True))} for w, r in rows("rules")]

    txs = []
    for where, r in rows("transactions"):
        t_tags = r.get("tags", [])
        if not isinstance(t_tags, list) or any(not isinstance(x, str) or len(x) > 30 for x in t_tags):
            c.bad(where, "tags must be a list of names")
            t_tags = []
        txs.append({"name": c.text(r, "name", where, 120), "amount": c.money(r, "amount", where),
                    "date": c.date(r, "date", where), "kind": c.choice(r, "kind", where, (("expense",), ("income",))),
                    "category": cat_ref(r, "category", where), "account": acct_ref(r, "account", where),
                    "payee": c.text(r, "payee", where, 80, required=False), "note": c.text(r, "note", where, 1000, required=False),
                    "tags": t_tags, "split_group": r.get("split_group"), "reconciled": bool(r.get("reconciled", False))})
    out["transactions"] = txs

    out["transfers"] = [{"from": acct_ref(r, "from", w), "to": acct_ref(r, "to", w), "amount": c.money(r, "amount", w),
                         "date": c.date(r, "date", w), "note": c.text(r, "note", w, 200, required=False)}
                        for w, r in rows("transfers")]
    out["budgets"] = [{"category": cat_ref(r, "category", w, required=False), "month": c.month(r.get("month"), w),
                       "amount": c.money(r, "amount", w), "rollover": bool(r.get("rollover", False)),
                       "warn_percent": min(99, max(1, int(r.get("warn_percent", 80)))) if isinstance(r.get("warn_percent", 80), int) else 80}
                      for w, r in rows("budgets")]
    goals = []
    for w, r in rows("goals"):
        contribs = r.get("contributions", [])
        if not isinstance(contribs, list):
            c.bad(w, "contributions must be a list")
            contribs = []
        goals.append({"name": c.text(r, "name", w, 80), "target_amount": c.money(r, "target_amount", w),
                      "target_date": c.date(r, "target_date", w, required=False),
                      "account": acct_ref(r, "account", w), "category": cat_ref(r, "category", w, required=False),
                      "contributions": [{"amount": c.money(x, "amount", w, positive=False, signed=True),
                                         "date": c.date(x, "date", w), "note": c.text(x, "note", w, 200, required=False)}
                                        for x in contribs if isinstance(x, dict)]})
    out["goals"] = goals
    out["recurring"] = [{"name": c.text(r, "name", w, 120), "amount": c.money(r, "amount", w),
                         "kind": c.choice(r, "kind", w, (("expense",), ("income",))), "category": cat_ref(r, "category", w),
                         "payee": c.text(r, "payee", w, 80, required=False), "account": acct_ref(r, "account", w),
                         "note": c.text(r, "note", w, 1000, required=False),
                         "frequency": c.choice(r, "frequency", w, (("weekly",), ("monthly",))),
                         "start_date": c.date(r, "start_date", w), "end_date": c.date(r, "end_date", w, required=False),
                         "next_due": c.date(r, "next_due", w), "active": bool(r.get("active", True))}
                        for w, r in rows("recurring")]
    out["views"] = [{"name": c.text(r, "name", w, 60), "query": c.text(r, "query", w, 500, required=False)} for w, r in rows("views")]
    locks = data.get("locked_months", [])
    out["locked_months"] = [c.month(m, "locked_months") for m in locks] if isinstance(locks, list) else []
    people = []
    for w, r in rows("people"):
        entries = r.get("entries", [])
        entries = entries if isinstance(entries, list) else []
        people.append({"name": c.text(r, "name", w, 60), "entries": [{
            "kind": c.choice(x, "kind", w, LEDGER_KINDS), "amount": c.money(x, "amount", w, positive=False, signed=True),
            "description": c.text(x, "description", w, 120, required=False), "date": c.date(x, "date", w),
            "due_date": c.date(x, "due_date", w, required=False)} for x in entries if isinstance(x, dict)]})
    out["people"] = people
    if c.problems:
        raise BackupError(c.problems)
    return out


def summary(parsed):
    return {key: len(parsed[key]) for key in ("accounts", "categories", "transactions", "transfers", "budgets", "goals",
                                              "recurring", "people", "tags", "rules", "views")}


def erase(user):
    """Remove every record the user owns (the account itself stays)."""
    for model in (Transfer, Budget, CategoryRule, RecurringTransaction, SavedView, MonthLock, Person):
        model.objects.filter(user=user).delete()
    Goal.objects.filter(user=user).delete()
    Transaction.all_objects.filter(user=user).delete()
    AuditEntry.objects.filter(user=user).delete()
    Category.objects.filter(user=user).update(parent=None)
    Category.objects.filter(user=user).delete()
    Tag.objects.filter(user=user).delete()
    Account.objects.filter(user=user).delete()


@transaction.atomic
def restore(user, parsed):
    """Replace all of the user's data with the validated backup."""
    with services.locked(user):
        erase(user)
        p = parsed["profile"]
        profile = services.get_profile(user)
        if p:
            profile.currency_code = p.get("currency_code", profile.currency_code).upper()[:3]
            profile.currency_symbol = p.get("currency_symbol", profile.currency_symbol)
            profile.number_format = p.get("number_format", profile.number_format)
            profile.allow_negative_balance = p.get("allow_negative_balance") if isinstance(p.get("allow_negative_balance"), bool) else None
            profile.secondary_currency_code = (p.get("secondary_currency_code") or "")[:3].upper()
            try:
                rate = Decimal(str(p.get("secondary_rate"))) if p.get("secondary_rate") else None
            except InvalidOperation:
                rate = None
            profile.secondary_rate = rate if rate and rate > 0 else None
        profile.setup_done = True
        profile.save()
        accounts = {a["name"].lower(): Account.objects.create(user=user, name=a["name"], type=a["type"],
                                                              opening_balance=a["opening_balance"], archived=a["archived"])
                    for a in parsed["accounts"]}
        cats = {c["name"].lower(): Category.objects.create(user=user, name=c["name"], kind=c["kind"], color=c["color"], icon=c["icon"])
                for c in parsed["categories"]}
        for c in parsed["categories"]:
            if c["parent"]:
                parent = cats[c["parent"].lower()]
                child = cats[c["name"].lower()]
                if parent.pk != child.pk and not parent.parent_id:
                    child.parent = parent
                    child.save(update_fields=["parent"])
        tags = {t.lower(): Tag.objects.create(user=user, name=t) for t in dict.fromkeys(parsed["tags"])}
        for r in parsed["rules"]:
            CategoryRule.objects.create(user=user, pattern=r["pattern"], category=cats[r["category"].lower()],
                                        priority=r["priority"], active=r["active"])
        import uuid
        groups = {}
        for t in parsed["transactions"]:
            group = None
            if t["split_group"]:
                group = groups.setdefault(t["split_group"], uuid.uuid4())
            tx = Transaction.objects.create(
                user=user, name=t["name"], amount=t["amount"], date=t["date"], kind=t["kind"], category=cats[t["category"].lower()],
                account=accounts.get(t["account"].lower()) if t["account"] else None, payee=t["payee"], note=t["note"],
                split_group=group, reconciled=t["reconciled"])
            if t["tags"]:
                found = []
                for name in t["tags"]:
                    tag = tags.get(name.lower()) or tags.setdefault(name.lower(), Tag.objects.create(user=user, name=name))
                    found.append(tag)
                tx.tags.set(found)
        for t in parsed["transfers"]:
            Transfer.objects.create(user=user, from_account=accounts[t["from"].lower()], to_account=accounts[t["to"].lower()],
                                    amount=t["amount"], date=t["date"], note=t["note"])
        for b in parsed["budgets"]:
            Budget.objects.create(user=user, category=cats[b["category"].lower()] if b["category"] else None, month=b["month"],
                                  amount=b["amount"], rollover=b["rollover"], warn_percent=b["warn_percent"])
        for g in parsed["goals"]:
            goal = Goal.objects.create(user=user, name=g["name"], target_amount=g["target_amount"], target_date=g["target_date"],
                                       account=accounts.get(g["account"].lower()) if g["account"] else None,
                                       category=cats.get(g["category"].lower()) if g["category"] else None)
            for x in g["contributions"]:
                Contribution.objects.create(goal=goal, amount=x["amount"], date=x["date"], note=x["note"])
        for r in parsed["recurring"]:
            RecurringTransaction.objects.create(
                user=user, name=r["name"], amount=r["amount"], kind=r["kind"], category=cats[r["category"].lower()], payee=r["payee"],
                account=accounts.get(r["account"].lower()) if r["account"] else None, note=r["note"], frequency=r["frequency"],
                start_date=r["start_date"], end_date=r["end_date"], next_due=r["next_due"], active=r["active"])
        for v in parsed["views"]:
            SavedView.objects.get_or_create(user=user, name=v["name"], defaults={"query": v["query"]})
        for m in parsed["locked_months"]:
            MonthLock.objects.get_or_create(user=user, month=m)
        for person in parsed["people"]:
            obj = Person.objects.create(user=user, name=person["name"])
            for e in person["entries"]:
                LedgerEntry.objects.create(person=obj, kind=e["kind"], amount=e["amount"], description=e["description"],
                                           date=e["date"], due_date=e["due_date"])
        if not Account.objects.filter(user=user).exists():
            services.default_account(user)
    services.forget_profile(user)
