"""Plain-language insights: how the month is going, what changed, upcoming bills and subscriptions."""
import calendar
import datetime
from collections import defaultdict
from statistics import median

from django.db.models import Count, Q, Sum
from django.utils import timezone

from . import budgeting, services
from .formatting import format_money
from .models import Goal, LedgerEntry, Person, RecurringTransaction, Transaction
from .services import ZERO, add_months, month_end, month_start, q2

UNUSUAL_PERCENT = 50        # a category this far above its 3-month average is flagged
BILL_WINDOW_DAYS = 14
DUE_SOON_DAYS = 3


def _spent_by_category(user, start, end):
    rows = (Transaction.objects.filter(user=user, kind="expense", date__gte=start, date__lte=end)
            .values("category_id", "category__name", "category__color").annotate(t=Sum("amount")))
    return {r["category_id"]: (r["category__name"], r["category__color"], q2(r["t"])) for r in rows}


def movers(user, today):
    """Categories whose spending so far this month changed most compared with the same days last month."""
    this_start = month_start(today)
    prev_start = add_months(this_start, -1)
    prev_end = prev_start.replace(day=min(today.day, calendar.monthrange(prev_start.year, prev_start.month)[1]))
    now = _spent_by_category(user, this_start, today)
    before = _spent_by_category(user, prev_start, prev_end)
    diffs = []
    for cid in set(now) | set(before):
        name, color, a = now.get(cid, (None, None, ZERO))
        pname, pcolor, b = before.get(cid, (None, None, ZERO))
        diffs.append({"name": name or pname, "color": color or pcolor, "now": a, "before": b, "change": a - b})
    up = sorted((d for d in diffs if d["change"] > 0), key=lambda d: -d["change"])[:3]
    down = sorted((d for d in diffs if d["change"] < 0), key=lambda d: d["change"])[:3]
    return {"up": up, "down": down}


def unusual(user, today):
    """Categories already far above their average of the previous three complete months."""
    this_start = month_start(today)
    first = add_months(this_start, -3)
    history = defaultdict(lambda: ZERO)
    names = {}
    rows = (Transaction.objects.filter(user=user, kind="expense", date__gte=first, date__lt=this_start)
            .values("category_id", "category__name").annotate(t=Sum("amount")))
    for r in rows:
        history[r["category_id"]] = q2(r["t"]) / 3
        names[r["category_id"]] = r["category__name"]
    now = _spent_by_category(user, this_start, today)
    out = []
    for cid, (name, color, spent) in now.items():
        avg = history.get(cid, ZERO)
        if avg > 0 and spent > avg * (100 + UNUSUAL_PERCENT) / 100:
            out.append({"name": name, "color": color, "spent": spent, "average": q2(avg),
                        "percent": round(float(spent / avg * 100))})
    return sorted(out, key=lambda d: -d["percent"])[:3]


def subscriptions(user, today):
    """Payees (or descriptions) that repeat about monthly with a similar amount."""
    first = add_months(month_start(today), -4)
    groups = defaultdict(list)
    for t in (Transaction.objects.filter(user=user, kind="expense", date__gte=first, date__lte=today)
              .select_related("category")):
        key = (t.payee or t.name).strip().lower()
        if key:
            groups[key].append(t)
    tracked = {r.name.strip().lower() for r in RecurringTransaction.objects.filter(user=user)}
    found = []
    for key, items in groups.items():
        months = defaultdict(list)
        for t in items:
            months[month_start(t.date)].append(t)
        if len(months) < 3 or any(len(v) > 2 for v in months.values()):
            continue
        amounts = [float(t.amount) for t in items]
        mid = median(amounts)
        if mid <= 0 or any(abs(a - mid) / mid > 0.15 for a in amounts):
            continue
        last = max(items, key=lambda t: t.date)
        found.append({
            "name": last.payee or last.name, "amount": last.amount, "months": len(months),
            "category": last.category.name, "last_date": last.date,
            "next_date": add_months(last.date, 1), "tracked": last.name.strip().lower() in tracked or key in tracked,
        })
    return sorted(found, key=lambda d: -d["amount"])[:6]


def bills(user, today):
    """Recurring expenses (and dated debts) coming due soon, soonest first."""
    horizon = today + datetime.timedelta(days=BILL_WINDOW_DAYS)
    out = []
    for r in (RecurringTransaction.objects.filter(user=user, active=True, kind="expense", next_due__lte=horizon)
              .select_related("category")):
        out.append({"type": "bill", "id": r.pk, "name": r.name, "amount": r.amount, "due": r.next_due,
                    "days": (r.next_due - today).days, "category": r.category.name})
    for person in Person.objects.filter(user=user):
        net = person.entries.aggregate(t=Sum("amount"))["t"] or ZERO
        if net == 0:
            continue
        due = (person.entries.filter(due_date__isnull=False, kind__in=("lent", "borrowed"), due_date__lte=horizon)
               .order_by("due_date").first())
        if due:
            out.append({"type": "debt", "id": person.pk, "name": f"{person.name} ({'owes you' if net > 0 else 'you owe'})",
                        "amount": abs(net), "due": due.due_date, "days": (due.due_date - today).days, "category": ""})
    return sorted(out, key=lambda b: b["due"])


def _money(user, value):
    return format_money(value, services.get_profile(user))


def sentences(user, today=None):
    """The headline sentences for the dashboard."""
    today = today or timezone.localdate()
    this_start = month_start(today)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    left = days_in_month - today.day
    out = []
    income, expense = services.income_expense(user, this_start, today)

    # budget health
    data = budgeting.status(user, today, today)
    items = ([data["overall"]] if data["overall"] else []) + sorted(data["categories"], key=lambda i: -i["percent"])
    for item in items[:3]:
        name = item["category"]["name"] if item["category"] else "monthly"
        label = f"your {name} budget" if item["category"] else "this month's budget"
        if item["over"]:
            out.append({"level": "bad", "text": f"You are over {label} by {_money(user, -item['remaining'])}.", "url": "/budgets/"})
        elif item["percent"] >= 50:
            days = f"{left} day{'s' if left != 1 else ''}"
            out.append({"level": "warn" if item["level"] == "warn" else "info",
                        "text": f"You have spent {item['percent']:.0f}% of {label} with {days} left.", "url": "/budgets/"})

    # pace against last month
    prev_start = add_months(this_start, -1)
    prev_end = prev_start.replace(day=min(today.day, calendar.monthrange(prev_start.year, prev_start.month)[1]))
    _, prev_expense = services.income_expense(user, prev_start, prev_end)
    if expense and prev_expense:
        change = round(float((expense - prev_expense) / prev_expense * 100))
        word = "less" if change < 0 else "more"
        if change == 0:
            out.append({"level": "info", "text": "You are spending about the same as at this point last month.", "url": "/analytics/"})
        else:
            out.append({"level": "good" if change < 0 else "warn",
                        "text": f"You have spent {_money(user, expense)} so far, {abs(change)}% {word} than at this point last month.",
                        "url": "/analytics/"})

    # forecast
    if today.day >= 3 and expense:
        projected = q2(expense / today.day * days_in_month)
        out.append({"level": "info", "text": f"At this pace you will spend about {_money(user, projected)} by the end of the month.",
                    "url": "/budgets/"})

    for u in unusual(user, today)[:2]:
        out.append({"level": "warn", "text": f"{u['name']} is already at {u['percent']}% of its usual monthly spending "
                                             f"({_money(user, u['average'])} on average).", "url": "/analytics/"})
    upcoming = [b for b in bills(user, today) if b["days"] <= DUE_SOON_DAYS]
    for b in upcoming[:2]:
        when = "is overdue" if b["days"] < 0 else "is due today" if b["days"] == 0 else f"is due in {b['days']} day{'s' if b['days'] != 1 else ''}"
        out.append({"level": "warn", "text": f"{b['name']} ({_money(user, b['amount'])}) {when}.",
                    "url": "/recurring/" if b["type"] == "bill" else "/people/"})
    if income and expense and income > 0:
        rate = round(float((income - expense) / income * 100))
        if rate >= 20:
            out.append({"level": "good", "text": f"You have kept {rate}% of this month's income so far.", "url": "/reports/"})
    return out


def goal_progress(user, today=None):
    rows = []
    for g in Goal.objects.filter(user=user):
        info = budgeting.goal_summary(g, today)
        rows.append({"id": g.pk, "name": g.name, "percent": info["percent"], "saved": info["saved"], "target": g.target_amount,
                     "required_monthly": info["required_monthly"], "complete": info["complete"]})
    return sorted(rows, key=lambda r: (r["complete"], -r["percent"]))[:4]


def insights(user, today=None):
    today = today or timezone.localdate()
    return {
        "sentences": sentences(user, today), "movers": movers(user, today), "subscriptions": subscriptions(user, today),
        "bills": bills(user, today), "goals": goal_progress(user, today),
    }


def weekly_digest(user, today=None):
    today = today or timezone.localdate()
    end = today
    start = today - datetime.timedelta(days=6)
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=6)
    income, expense = services.income_expense(user, start, end)
    prev_income, prev_expense = services.income_expense(user, prev_start, prev_end)
    cats = sorted(_spent_by_category(user, start, end).values(), key=lambda v: -v[2])[:5]
    biggest = (Transaction.objects.filter(user=user, kind="expense", date__gte=start, date__lte=end)
               .select_related("category").order_by("-amount").first())
    return {
        "start": start, "end": end, "prev_start": prev_start, "prev_end": prev_end,
        "income": income, "expense": expense, "net": income - expense,
        "prev_income": prev_income, "prev_expense": prev_expense,
        "expense_change": round(float((expense - prev_expense) / prev_expense * 100)) if prev_expense else None,
        "categories": [{"name": n, "color": c, "total": t} for n, c, t in cats],
        "biggest": biggest,
        "count": Transaction.objects.filter(user=user, date__gte=start, date__lte=end).count(),
        "bills": bills(user, today), "budget": budgeting.status(user, today, today)["totals"],
    }
