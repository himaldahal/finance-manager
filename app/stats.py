"""Read-only aggregations behind the dashboard and analytics."""
import datetime
from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from . import budgeting, services
from .models import Category, Goal, Transaction
from .services import ZERO, add_months, month_end, month_start, q2

MAX_RANGE_DAYS = 731
HEATMAP_WEEKS = 26


def pct_change(current, previous):
    if not previous:
        return None
    return round(float((current - previous) / previous * 100), 1)


def month_totals(user, month):
    income, expense = services.income_expense(user, month, month_end(month))
    net = income - expense
    rate = round(float(net / income * 100), 1) if income > 0 else None
    return {"income": income, "expense": expense, "net": net, "savings_rate": rate}


def summary(user, month):
    current = month_totals(user, month)
    previous = month_totals(user, add_months(month, -1))
    return {
        "month": month.strftime("%Y-%m"),
        "balance": services.balance_for(user),
        **current,
        "previous": previous,
        "changes": {
            "income": pct_change(current["income"], previous["income"]),
            "expense": pct_change(current["expense"], previous["expense"]),
            "net": pct_change(current["net"], previous["net"]) if previous["net"] > 0 else None,
        },
    }


def clamp_range(start, end):
    if end < start:
        start, end = end, start
    if (end - start).days > MAX_RANGE_DAYS:
        start = end - datetime.timedelta(days=MAX_RANGE_DAYS)
    return start, end


def scoped(user, category=None, tag=None):
    """Transactions of the user, optionally limited to a category (and its sub-categories) and a tag."""
    qs = Transaction.objects.filter(user=user)
    if category:
        qs = qs.filter(Q(category_id=category) | Q(category__parent_id=category))
    if tag:
        qs = qs.filter(tags__id=tag, tags__user=user)
    return qs


def _by_month(qs, first, last):
    rows = (qs.filter(date__gte=first, date__lte=last).annotate(m=TruncMonth("date")).values("m")
            .annotate(income=Sum("amount", filter=Q(kind="income")), expense=Sum("amount", filter=Q(kind="expense"))))
    return {r["m"]: (q2(r["income"] or ZERO), q2(r["expense"] or ZERO)) for r in rows}


def analytics(user, start, end, category=None, tag=None, today=None):
    start, end = clamp_range(start, end)
    base = scoped(user, category, tag)
    inrange = base.filter(date__gte=start, date__lte=end)
    first = add_months(month_start(end), -11)
    months = [add_months(first, i) for i in range(12)]

    by_month = _by_month(base, first, month_end(end))
    monthly = []
    for m in months:
        income, expense = by_month.get(m, (ZERO, ZERO))
        monthly.append({"month": m.strftime("%Y-%m"), "income": income, "expense": expense, "net": income - expense})

    cat_rows = list(
        inrange.filter(kind="expense").values("category_id", "category__name", "category__color", "category__icon")
        .annotate(total=Sum("amount"), count=Count("id")).order_by("-total"))
    expense_total = sum((r["total"] for r in cat_rows), ZERO)
    categories = [{
        "id": r["category_id"], "name": r["category__name"], "color": r["category__color"], "icon": r["category__icon"],
        "total": q2(r["total"]), "count": r["count"],
        "share": round(float(r["total"] / expense_total * 100), 1) if expense_total else 0,
    } for r in cat_rows]

    # per-category monthly series for the biggest categories (sparklines and stacked bars)
    top_ids = [c["id"] for c in categories[:5]]
    series_rows = (base.filter(kind="expense", date__gte=first, date__lte=month_end(end))
                   .annotate(m=TruncMonth("date")).values("category_id", "m").annotate(t=Sum("amount")))
    per = defaultdict(lambda: defaultdict(lambda: ZERO))
    for r in series_rows:
        per[r["category_id"]][r["m"]] += r["t"]
    month_total = defaultdict(lambda: ZERO)
    for cid, data in per.items():
        for m, t in data.items():
            month_total[m] += t
    known = {c["id"]: c for c in categories}
    names = {c.pk: c for c in Category.objects.filter(user=user, pk__in=set(per) | set(top_ids))}

    def series_for(cid):
        meta = known.get(cid) or {"name": names[cid].name, "color": names[cid].color}
        return {"id": cid, "name": meta["name"], "color": meta["color"],
                "values": [q2(per[cid].get(m, ZERO)) for m in months]}

    trend = [series_for(c["id"]) for c in categories[:6]]
    stacked_series = [series_for(cid) for cid in top_ids]
    other = [q2(month_total.get(m, ZERO) - sum((s["values"][i] for s in stacked_series), ZERO)) for i, m in enumerate(months)]
    if any(other):
        stacked_series.append({"id": None, "name": "Other", "color": "gray", "values": other})
    stacked = {"months": [m.strftime("%Y-%m") for m in months], "series": stacked_series}

    opening = services.balance_for(user, before=start)
    daily_rows = {r["date"]: r for r in base.filter(date__gte=start, date__lte=end).values("date").annotate(
        income=Sum("amount", filter=Q(kind="income")), expense=Sum("amount", filter=Q(kind="expense")))}
    all_rows = {r["date"]: r for r in Transaction.objects.filter(user=user, date__gte=start, date__lte=end).values("date").annotate(
        income=Sum("amount", filter=Q(kind="income")), expense=Sum("amount", filter=Q(kind="expense")))}
    daily = []
    running = opening
    day = start
    while day <= end:
        row = daily_rows.get(day, {})
        real = all_rows.get(day, {})
        income, expense = q2(row.get("income") or ZERO), q2(row.get("expense") or ZERO)
        running += q2(real.get("income") or ZERO) - q2(real.get("expense") or ZERO)
        daily.append({"date": day.isoformat(), "income": income, "expense": expense, "balance": running})
        day += datetime.timedelta(days=1)

    # weekday pattern
    weekday_totals = [ZERO] * 7
    weekday_days = [0] * 7
    for item in daily:
        d = datetime.date.fromisoformat(item["date"])
        weekday_totals[d.weekday()] += item["expense"]
        weekday_days[d.weekday()] += 1
    weekday = [{"day": n, "total": q2(weekday_totals[i]),
                "average": q2(weekday_totals[i] / weekday_days[i]) if weekday_days[i] else ZERO}
               for i, n in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))]

    # heatmap: last 26 weeks ending at ``end``, weeks start on Monday
    heat_end = end
    heat_start = heat_end - datetime.timedelta(days=heat_end.weekday() + 7 * (HEATMAP_WEEKS - 1))
    heat_rows = {r["date"]: q2(r["t"]) for r in base.filter(kind="expense", date__gte=heat_start, date__lte=heat_end)
                 .values("date").annotate(t=Sum("amount"))}
    heatmap = {"start": heat_start.isoformat(), "end": heat_end.isoformat(),
               "days": [{"date": (heat_start + datetime.timedelta(days=i)).isoformat(),
                         "expense": heat_rows.get(heat_start + datetime.timedelta(days=i), ZERO)}
                        for i in range((heat_end - heat_start).days + 1)]}

    # cumulative spending against the budget for the month of ``end``
    cm = month_start(end)
    budget_data = budgeting.status(user, cm, today)
    limit = None
    if budget_data["overall"]:
        limit = budget_data["overall"]["available"]
    elif budget_data["categories"]:
        limit = budget_data["totals"]["limit"]
    month_days = {r["date"]: q2(r["t"]) for r in base.filter(kind="expense", date__gte=cm, date__lte=month_end(cm))
                  .values("date").annotate(t=Sum("amount"))}
    running_spend = ZERO
    cumulative = []
    for i in range((month_end(cm) - cm).days + 1):
        d = cm + datetime.timedelta(days=i)
        running_spend += month_days.get(d, ZERO)
        cumulative.append({"date": d.isoformat(), "spent": running_spend})
    cumulative_spend = {"month": cm.strftime("%Y-%m"), "limit": limit, "days": cumulative}

    budget_vs_actual = [
        {"name": i["category"]["name"] if i["category"] else "Overall", "color": i["category"]["color"] if i["category"] else "blue",
         "limit": i["available"], "spent": i["spent"]} for i in budget_data["items"]]

    payees = [{"name": r["payee"], "total": q2(r["t"]), "count": r["c"]} for r in
              inrange.filter(kind="expense").exclude(payee="").values("payee").annotate(t=Sum("amount"), c=Count("id")).order_by("-t")[:8]]

    top = [{"id": t.pk, "name": t.name, "amount": t.amount, "date": t.date.isoformat(),
            "category": {"id": t.category_id, "name": t.category.name, "color": t.category.color}}
           for t in inrange.filter(kind="expense").select_related("category").order_by("-amount", "-date", "-id")[:5]]

    goals = []
    for g in Goal.objects.filter(user=user):
        info = budgeting.goal_summary(g, today)
        goals.append({"id": g.pk, "name": g.name, "target": g.target_amount, "saved": info["saved"], "percent": info["percent"]})

    income, expense = services.income_expense_for(inrange)
    return {
        "start": start.isoformat(), "end": end.isoformat(), "opening_balance": opening,
        "totals": {"income": income, "expense": expense, "net": income - expense},
        "monthly": monthly, "categories": categories, "trend": trend, "stacked": stacked, "daily": daily,
        "weekday": weekday, "heatmap": heatmap, "cumulative": cumulative_spend, "budget_vs_actual": budget_vs_actual,
        "payees": payees, "top": top, "goals": goals,
    }
