"""Business rules: balances, overdraft policy, defaults and recurring items."""
import calendar
import datetime
from contextlib import contextmanager
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .formatting import format_money
from .models import (
    Account, AuditEntry, Category, CategoryRule, MonthLock, Profile, RecurringTransaction, Tag, Transaction, Transfer,
)

ZERO = Decimal("0.00")
CENT = Decimal("0.01")

DEFAULT_CATEGORIES = (
    # name, kind, colour, icon
    ("Salary", "income", "green", "banknote"),
    ("Other income", "income", "olive", "coins"),
    ("Groceries", "expense", "teal", "shopping-cart"),
    ("Rent", "expense", "plum", "house"),
    ("Utilities", "expense", "blue", "zap"),
    ("Transport", "expense", "amber", "bus"),
    ("Dining out", "expense", "red", "utensils"),
    ("Health", "expense", "teal", "heart-pulse"),
    ("Shopping", "expense", "gray", "shopping-bag"),
    ("Other", "both", "gray", "ellipsis"),
)


def q2(value):
    return Decimal(value).quantize(CENT)


def get_profile(user):
    profile = getattr(user, "_profile_cache", None)
    if profile is None:
        profile, _ = Profile.objects.get_or_create(
            user=user,
            defaults={
                "currency_code": settings.DEFAULT_CURRENCY_CODE,
                "currency_symbol": settings.DEFAULT_CURRENCY_SYMBOL,
            },
        )
        user._profile_cache = profile
    return profile


def forget_profile(user):
    user.__dict__.pop("_profile_cache", None)


def create_default_categories(user):
    existing = {n.lower() for n in Category.objects.filter(user=user).values_list("name", flat=True)}
    Category.objects.bulk_create(
        Category(user=user, name=name, kind=kind, color=color, icon=icon)
        for name, kind, color, icon in DEFAULT_CATEGORIES
        if name.lower() not in existing
    )


def default_account(user):
    """The account new transactions go to (created on first use)."""
    account = Account.objects.filter(user=user, archived=False).order_by("id").first()
    if account is None:
        account = Account.objects.create(user=user, name="Main account", type="bank")
    return account


def set_up_new_user(user):
    """Defaults every account needs: categories and a first account."""
    create_default_categories(user)
    default_account(user)


# --- month helpers -----------------------------------------------------------

def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def add_months(day, months, anchor_day=None):
    """Add months, clamping the day to the target month's length."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    wanted = anchor_day or day.day
    return datetime.date(year, month, min(wanted, calendar.monthrange(year, month)[1]))


def parse_month(value, default=None):
    """Parse 'YYYY-MM' to the first day of that month; fall back to ``default``."""
    default = default or month_start(timezone.localdate())
    try:
        year, month = str(value).split("-")
        parsed = datetime.date(int(year), int(month), 1)
    except (ValueError, TypeError):
        return default
    return parsed if parsed.year >= 2000 else default


# --- balances ----------------------------------------------------------------

def _net(qs):
    totals = qs.order_by().aggregate(
        income=Sum("amount", filter=Q(kind="income")),
        expense=Sum("amount", filter=Q(kind="expense")),
    )
    return q2(totals["income"] or ZERO), q2(totals["expense"] or ZERO)


def income_expense(user, start=None, end=None):
    qs = Transaction.objects.filter(user=user)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    return _net(qs)


def income_expense_for(queryset):
    """Income and expense totals of an arbitrary transaction queryset."""
    return _net(queryset)


def balance_for(user, before=None):
    """Sum of account opening balances plus income minus expense (optionally before a date).

    Transfers move money between accounts and cancel out, so they do not appear here.
    """
    opening = Account.objects.filter(user=user).aggregate(total=Sum("opening_balance"))["total"] or ZERO
    income, expense = income_expense(user, end=before - datetime.timedelta(days=1) if before else None)
    return q2(opening + income - expense)


def account_balances(user):
    """{account_id: Decimal} for all of the user's accounts, in a handful of queries."""
    balances = {a.pk: q2(a.opening_balance) for a in Account.objects.filter(user=user)}
    rows = Transaction.objects.filter(user=user, account__isnull=False).values("account_id").annotate(
        income=Sum("amount", filter=Q(kind="income")), expense=Sum("amount", filter=Q(kind="expense")))
    for r in rows:
        balances[r["account_id"]] += q2(r["income"] or ZERO) - q2(r["expense"] or ZERO)
    for r in Transfer.objects.filter(user=user).values("from_account_id").annotate(t=Sum("amount")):
        balances[r["from_account_id"]] -= q2(r["t"])
    for r in Transfer.objects.filter(user=user).values("to_account_id").annotate(t=Sum("amount")):
        balances[r["to_account_id"]] += q2(r["t"])
    return balances


def account_balance(account):
    return account_balances(account.user).get(account.pk, ZERO)


def allows_negative(user):
    preference = get_profile(user).allow_negative_balance
    return settings.ALLOW_NEGATIVE_BALANCE if preference is None else preference


class InsufficientFunds(ValidationError):
    pass


@contextmanager
def locked(user):
    """Serialise balance-affecting writes for one user."""
    with transaction.atomic():
        Profile.objects.select_for_update().filter(user=user).first()
        forget_profile(user)
        yield


def ensure_funds(user, delta, account=None):
    """Raise InsufficientFunds if applying ``delta`` would overdraw a disallowed account.

    Credit accounts may go negative. Without an account the overall balance is checked.
    """
    if delta >= 0 or allows_negative(user):
        return
    if account is not None:
        if account.is_credit:
            return
        current = account_balance(account)
        label = f"{account.name} balance"
    else:
        current = balance_for(user)
        label = "balance"
    if current + delta < 0:
        raise InsufficientFunds(
            f"This would take your {label} below zero "
            f"(currently {format_money(current, get_profile(user))}). "
            "Allow negative balances in Settings to proceed."
        )


def ensure_effects(user, effects):
    """``effects`` is a list of (account_or_None, delta); sums per account before checking."""
    grouped = {}
    for account, delta in effects:
        key = account.pk if account is not None else None
        entry = grouped.setdefault(key, [account, ZERO])
        entry[1] += delta
    for account, delta in grouped.values():
        ensure_funds(user, delta, account)


def is_overdrawn(user):
    return balance_for(user) < 0


# --- rules, tags ------------------------------------------------------------

def suggest_category(user, text, kind=None):
    """First active rule (by priority) whose pattern occurs in ``text``."""
    haystack = (text or "").lower()
    if not haystack:
        return None
    for rule in CategoryRule.objects.filter(user=user, active=True).select_related("category"):
        if rule.pattern.lower() in haystack and (kind is None or rule.category.accepts(kind)):
            return rule.category
    return None


def set_tags(tx, names):
    """Replace a transaction's tags with the named ones (created per user, case-insensitive)."""
    tags = []
    for name in names:
        name = " ".join(str(name).split())[:30]
        if not name:
            continue
        tag = Tag.objects.filter(user=tx.user, name__iexact=name).first() or Tag.objects.create(user=tx.user, name=name)
        if tag not in tags:
            tags.append(tag)
    tx.tags.set(tags[:10])


# --- closed months and the change log ----------------------------------------

class MonthClosed(ValidationError):
    pass


def locked_months(user):
    return set(MonthLock.objects.filter(user=user).values_list("month", flat=True))


def ensure_unlocked(user, *days):
    """Refuse changes to transactions dated in a closed month."""
    closed = locked_months(user)
    if not closed:
        return
    for day in days:
        if day and month_start(day) in closed:
            raise MonthClosed(
                f"{day:%B %Y} is closed, so its transactions cannot be changed. "
                "Reopen the month in Settings first."
            )


def snapshot(tx):
    return {
        "name": tx.name, "amount": f"{tx.amount:.2f}", "date": tx.date.isoformat(), "kind": tx.kind,
        "category": tx.category.name if tx.category_id else "", "account": tx.account.name if tx.account_id else "",
        "payee": tx.payee, "note": tx.note, "tags": sorted(t.name for t in tx.tags.all()) if tx.pk else [],
    }


def record(user, tx_id, action, summary="", before=None, after=None):
    AuditEntry.objects.create(user=user, transaction_id=tx_id, action=action, summary=summary[:300], before=before, after=after)


def changed_fields(before, after):
    return [key for key in after if before.get(key) != after.get(key)]


# --- transaction writes ------------------------------------------------------

def save_transaction(instance, tags=None, action=None):
    """Check the overdraft policy and closed months, save, and log the change, atomically."""
    user = instance.user
    with locked(user):
        if instance.account_id is None:
            instance.account = default_account(user)
        effects = [(instance.account, instance.effect)]
        days = [instance.date]
        before = None
        if instance.pk:
            old = Transaction.objects.select_related("account", "category").prefetch_related("tags").filter(pk=instance.pk).first()
            if old:
                effects.append((old.account, -old.effect))
                days.append(old.date)
                before = snapshot(old)
        ensure_unlocked(user, *days)
        ensure_effects(user, effects)
        instance.save()
        if tags is not None:
            set_tags(instance, tags)
        instance = Transaction.objects.select_related("account", "category").prefetch_related("tags").get(pk=instance.pk)
        after = snapshot(instance)
        if before is None:
            record(user, instance.pk, action or "created", f"Added {instance.name} ({instance.amount:.2f})", None, after)
        else:
            fields = changed_fields(before, after)
            if fields:
                record(user, instance.pk, "updated", "Changed " + ", ".join(fields), before, after)
    return instance


def delete_transactions(user, queryset):
    """Soft delete (kept in the trash for 30 days); returns the ids that were deleted."""
    with locked(user):
        rows = list(queryset.filter(user=user).select_related("account", "category"))
        ensure_unlocked(user, *[t.date for t in rows])
        ensure_effects(user, [(t.account, -t.effect) for t in rows])
        ids = [t.pk for t in rows]
        Transaction.objects.filter(pk__in=ids).update(deleted_at=timezone.now())
        for t in rows:
            record(user, t.pk, "deleted", f"Deleted {t.name} ({t.amount:.2f})", snapshot(t), None)
    return ids


def restore_transactions(user, ids):
    with locked(user):
        qs = Transaction.all_objects.filter(user=user, pk__in=ids, deleted_at__isnull=False)
        rows = list(qs.select_related("account", "category"))
        ensure_unlocked(user, *[t.date for t in rows])
        ensure_effects(user, [(t.account, t.effect) for t in rows])
        qs.update(deleted_at=None)
        for t in rows:
            record(user, t.pk, "restored", f"Restored {t.name}", None, snapshot(t))
    return [t.pk for t in rows]


def change_category(user, ids, category):
    with locked(user):
        rows = list(Transaction.objects.filter(user=user, pk__in=ids).select_related("category", "account"))
        ensure_unlocked(user, *[t.date for t in rows])
        for t in rows:
            if t.category_id != category.pk:
                record(user, t.pk, "updated", "Changed category", {"category": t.category.name}, {"category": category.name})
        Transaction.objects.filter(pk__in=[t.pk for t in rows]).update(category=category, updated_at=timezone.now())


def set_reconciled(user, ids, value):
    Transaction.objects.filter(user=user, pk__in=ids).update(reconciled=value)


def create_split(user, base, parts, tags=None):
    """One purchase over several categories: one transaction per part, linked by ``split_group``.

    ``base`` is an unsaved Transaction with the shared fields; ``parts`` is [(category, amount)].
    """
    import uuid

    with locked(user):
        group = uuid.uuid4()
        if base.account_id is None:
            base.account = default_account(user)
        total = sum((amount for _, amount in parts), ZERO)
        ensure_unlocked(user, base.date)
        ensure_effects(user, [(base.account, total if base.kind == "income" else -total)])
        made = []
        for category, amount in parts:
            tx = Transaction(user=user, name=base.name, amount=amount, date=base.date, kind=base.kind, category=category,
                             account=base.account, payee=base.payee, note=base.note, split_group=group)
            tx.save()
            if tags:
                set_tags(tx, tags)
            made.append(tx)
            record(user, tx.pk, "created", f"Added {tx.name} ({tx.amount:.2f}), part of a split", None,
                   snapshot(Transaction.objects.select_related("category", "account").get(pk=tx.pk)))
    return made


def create_transfer(transfer):
    with locked(transfer.user):
        ensure_unlocked(transfer.user, transfer.date)
        ensure_funds(transfer.user, -transfer.amount, transfer.from_account)
        transfer.save()
    return transfer


def delete_transfer(transfer):
    with locked(transfer.user):
        ensure_unlocked(transfer.user, transfer.date)
        ensure_funds(transfer.user, -transfer.amount, transfer.to_account)
        transfer.delete()


TRASH_DAYS = 30


def purge_deleted(older_than=datetime.timedelta(days=TRASH_DAYS)):
    cutoff = timezone.now() - older_than
    count, _ = Transaction.all_objects.filter(deleted_at__lt=cutoff).delete()
    return count


# --- recurring ---------------------------------------------------------------

def following_date(item, current):
    if item.frequency == RecurringTransaction.WEEKLY:
        return current + datetime.timedelta(weeks=1)
    return add_months(current, 1, anchor_day=item.start_date.day)


def first_due_on_or_after(item, day):
    due = item.start_date
    # jump close to the target to keep this cheap for old schedules
    if item.frequency == RecurringTransaction.WEEKLY:
        if due < day:
            due += datetime.timedelta(weeks=(day - due).days // 7)
    else:
        months = (day.year - due.year) * 12 + day.month - due.month - 1
        if months > 0:
            due = add_months(due, months, anchor_day=item.start_date.day)
    while due < day:
        due = following_date(item, due)
    return due


MAX_CATCH_UP = 400


def apply_recurring_item(item, today=None):
    """Create every due occurrence of one item. Idempotent. Returns the count."""
    today = today or timezone.localdate()
    created = 0
    if not item.active:
        return created
    error = ""
    guard = 0
    while item.next_due <= today and guard < MAX_CATCH_UP:
        guard += 1
        due = item.next_due
        if item.end_date and due > item.end_date:
            break
        if not Transaction.all_objects.filter(recurring=item, recurring_date=due).exists():
            tx = Transaction(
                user=item.user, name=item.name, amount=item.amount, kind=item.kind,
                category=item.category, note=item.note, date=due, payee=item.payee,
                account=item.account or default_account(item.user),
                recurring=item, recurring_date=due,
            )
            try:
                with transaction.atomic():
                    ensure_unlocked(item.user, due)
                    ensure_funds(item.user, tx.effect, tx.account)
                    tx.save()
                    record(item.user, tx.pk, "created", f"Added {tx.name} from a recurring item", None, snapshot(tx))
                created += 1
            except ValidationError as exc:
                error = "; ".join(exc.messages)[:200]
                break
            except IntegrityError:  # a concurrent run created it first
                pass
        item.next_due = following_date(item, due)
    if item.end_date and item.next_due > item.end_date:
        item.active = False
    item.last_error = error
    item.save(update_fields=["next_due", "active", "last_error"])
    return created


def apply_due(user=None, today=None):
    today = today or timezone.localdate()
    items = RecurringTransaction.objects.filter(active=True, next_due__lte=today).select_related("user", "category")
    if user is not None:
        items = items.filter(user=user)
    total = 0
    for item in items:
        with locked(item.user):
            total += apply_recurring_item(item, today)
    return total
