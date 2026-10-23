"""Budget maths: spending, rollover, alerts, projections and history."""
import calendar
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Budget, Category, Goal, Transaction
from .services import ZERO, add_months, month_end, month_start, q2

ROLLOVER_LOOKBACK = 12


def category_rollup(user):
    """{category_id: category_id of the budget it counts towards (itself and its parent)}."""
    rollup = defaultdict(list)
    for cid, parent in Category.objects.filter(user=user).values_list("id", "parent_id"):
        rollup[cid].append(cid)
        if parent:
            rollup[cid].append(parent)
    return rollup


def spent_by_category(user, start, end):
    """({category_id: spent including sub-categories}, total spent) for a date range."""
    rollup = category_rollup(user)
    spent = defaultdict(lambda: ZERO)
    total = ZERO
    rows = (Transaction.objects.filter(user=user, kind="expense", date__gte=start, date__lte=end)
            .values("category_id").annotate(t=Sum("amount")))
    for row in rows:
        total += row["t"]
        for cid in rollup.get(row["category_id"], [row["category_id"]]):
            spent[cid] += row["t"]
    return spent, q2(total)


def monthly_spent(user, first, last):
    """{(category_id or None, month): spent}; None is all categories."""
    rollup = category_rollup(user)
    out = defaultdict(lambda: ZERO)
    rows = (Transaction.objects.filter(user=user, kind="expense", date__gte=first, date__lte=last)
            .annotate(m=TruncMonth("date")).values("category_id", "m").annotate(t=Sum("amount")))
    for row in rows:
        out[(None, row["m"])] += row["t"]
        for cid in rollup.get(row["category_id"], [row["category_id"]]):
            out[(cid, row["m"])] += row["t"]
    return out


def carry_over(user, category_id, month, spent_map):
    """Unspent amount carried into ``month`` from earlier months of rollover budgets."""
    first = add_months(month, -ROLLOVER_LOOKBACK)
    rows = Budget.objects.filter(user=user, category_id=category_id, month__gte=first, month__lt=month).order_by("month")
    carry = ZERO
    previous = None
    for row in rows:
        if previous is not None and add_months(previous, 1) != row.month:
            carry = ZERO
        available = row.amount + (carry if row.rollover else ZERO)
        carry = max(ZERO, available - spent_map.get((category_id, row.month), ZERO))
        previous = row.month
    if previous is not None and add_months(previous, 1) != month:
        carry = ZERO
    return q2(carry)


def week_buckets(month):
    days = calendar.monthrange(month.year, month.month)[1]
    return [(start, min(start + 6, days)) for start in range(1, days + 1, 7)]


def level_for(percent, warn):
    if percent >= 100:
        return "over"
    return "warn" if percent >= warn else "ok"


def pace(available, spent, month, today):
    """(projected month-end spend, safe-to-spend per day) for the month."""
    days = calendar.monthrange(month.year, month.month)[1]
    if month > month_start(today):
        return ZERO, q2(available / days)
    if month < month_start(today):
        return q2(spent), ZERO
    elapsed = max(today.day, 1)
    projected = q2(spent / elapsed * days)
    left = days - today.day + 1
    return projected, q2(max(ZERO, available - spent) / left)


def status(user, month, today=None):
    today = today or timezone.localdate()
    month = month_start(month)
    last = month_end(month)
    spent, total = spent_by_category(user, month, last)
    history_first = add_months(month, -ROLLOVER_LOOKBACK)
    spent_map = monthly_spent(user, history_first, month_start(month) - datetime.timedelta(days=1))
    expenses = list(Transaction.objects.filter(user=user, kind="expense", date__gte=month, date__lte=last)
                    .values_list("category_id", "date", "amount"))
    rollup = category_rollup(user)
    buckets = week_buckets(month)

    def weekly(category_id):
        sums = [ZERO] * len(buckets)
        for cid, day, amount in expenses:
            if category_id is None or category_id in rollup.get(cid, [cid]):
                sums[(day.day - 1) // 7] += amount
        return [q2(x) for x in sums]

    items = []
    for budget in Budget.objects.filter(user=user, month=month).select_related("category"):
        used = q2(total if budget.category_id is None else spent.get(budget.category_id, ZERO))
        carry = carry_over(user, budget.category_id, month, spent_map) if budget.rollover else ZERO
        available = budget.amount + carry
        percent = round(float(used / available * 100), 1)
        projected, safe = pace(available, used, month, today)
        items.append({
            "id": budget.pk,
            "category": None if budget.category_id is None else {
                "id": budget.category_id, "name": budget.category.name, "color": budget.category.color,
                "icon": budget.category.icon},
            "limit": budget.amount, "carry": carry, "available": available, "spent": used,
            "remaining": available - used, "percent": percent, "rollover": budget.rollover,
            "warn_percent": budget.warn_percent, "level": level_for(percent, budget.warn_percent),
            "over": used > available, "projected": projected, "projected_over": projected > available,
            "safe_per_day": safe, "weekly": weekly(budget.category_id),
            "weekly_limit": [q2(available * (e - s + 1) / calendar.monthrange(month.year, month.month)[1])
                             for s, e in buckets],
        })
    items.sort(key=lambda i: (i["category"] is not None, i["category"]["name"].lower() if i["category"] else ""))
    overall = next((i for i in items if i["category"] is None), None)
    categories = [i for i in items if i["category"] is not None]
    return {
        "month": month, "items": items, "overall": overall, "categories": categories,
        "weeks": [{"start": s, "end": e} for s, e in buckets],
        "totals": {
            "limit": q2(sum((i["available"] for i in categories), ZERO)),
            "spent": q2(sum((i["spent"] for i in categories), ZERO)),
            "over": sum(1 for i in items if i["over"]),
            "warn": sum(1 for i in items if i["level"] == "warn"),
            "all_spent": total,
        },
    }


def copy_month(user, source, target):
    """Copy budgets that the target month does not have yet. Returns the number created."""
    source, target = month_start(source), month_start(target)
    have = set(Budget.objects.filter(user=user, month=target).values_list("category_id", flat=True))
    created = 0
    for row in Budget.objects.filter(user=user, month=source):
        if row.category_id in have:
            continue
        Budget.objects.create(user=user, category_id=row.category_id, month=target, amount=row.amount,
                              rollover=row.rollover, warn_percent=row.warn_percent)
        created += 1
    return created


def history(user, months=12, today=None):
    today = today or timezone.localdate()
    first = add_months(month_start(today), -(months - 1))
    spent_map = monthly_spent(user, first, month_end(today))
    rows = []
    budgets = defaultdict(lambda: {"overall": None, "sum": ZERO, "count": 0})
    for b in Budget.objects.filter(user=user, month__gte=first, month__lte=today):
        entry = budgets[b.month]
        if b.category_id is None:
            entry["overall"] = b.amount
        else:
            entry["sum"] += b.amount
            entry["count"] += 1
    for i in range(months):
        month = add_months(first, i)
        entry = budgets.get(month)
        limit = None
        if entry:
            limit = entry["overall"] if entry["overall"] is not None else (entry["sum"] if entry["count"] else None)
        spent = q2(spent_map.get((None, month), ZERO))
        rows.append({"month": month.strftime("%Y-%m"), "limit": limit, "spent": spent,
                     "percent": round(float(spent / limit * 100), 1) if limit else None,
                     "over": bool(limit and spent > limit)})
    return rows


# --- goals -------------------------------------------------------------------

def goal_summary(goal, today=None):
    today = today or timezone.localdate()
    saved = q2(goal.contributions.aggregate(t=Sum("amount"))["t"] or ZERO)
    target = goal.target_amount
    remaining = max(ZERO, target - saved)
    percent = min(100.0, round(float(saved / target * 100), 1)) if target else 0.0
    required = None
    months_left = None
    if goal.target_date and remaining > 0:
        days = (goal.target_date - today).days
        months_left = max(1, -(-days // 30)) if days > 0 else 0
        required = q2(remaining / months_left) if months_left else remaining
    return {"saved": saved, "remaining": remaining, "percent": percent, "required_monthly": required,
            "months_left": months_left, "complete": saved >= target,
            "overdue": bool(goal.target_date and goal.target_date < today and saved < target)}


# --- notifications -----------------------------------------------------------

def notifications(user, today=None):
    """Alerts computed on demand: budget thresholds, failed recurring items, goals due."""
    from . import services

    today = today or timezone.localdate()
    out = []
    data = status(user, today, today)
    for item in data["items"]:
        name = item["category"]["name"] if item["category"] else "Overall budget"
        if item["level"] == "over":
            out.append({"level": "error", "kind": "budget", "text": f"{name} is over budget.", "url": "/budgets/"})
        elif item["level"] == "warn":
            out.append({"level": "warn", "kind": "budget",
                        "text": f"{name} has used {item['percent']:.0f}% of its budget.", "url": "/budgets/"})
    for rec in user.recurring.filter(active=True).exclude(last_error=""):
        out.append({"level": "warn", "kind": "recurring", "text": f"{rec.name} could not be recorded: {rec.last_error}",
                    "url": "/recurring/"})
    for goal in Goal.objects.filter(user=user, target_date__isnull=False):
        info = goal_summary(goal, today)
        if info["overdue"]:
            out.append({"level": "warn", "kind": "goal", "text": f"Goal “{goal.name}” is past its target date.",
                        "url": "/goals/"})
    if services.balance_for(user) < 0:
        out.append({"level": "warn", "kind": "balance", "text": "Your balance is below zero.", "url": "/accounts/"})
    return out
