"""Small JSON API used by the pages. Every endpoint is scoped to request.user."""
import datetime
import json
from decimal import Decimal
from functools import wraps

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from urllib.parse import urlencode

from . import services, stats
from .formatting import format_money
from .filters import TransactionFilter
from . import budgeting, demo, insights as insight_lib, nlq
from .forms import (
    AccountForm, BudgetForm, CategoryForm, ContributionForm, GoalForm, LedgerEntryForm, PersonForm, RecurringForm, RuleForm,
    SavedViewForm, SplitForm, TransactionForm, TransferForm,
)
from .models import (
    Account, AuditEntry, Budget, Category, CategoryRule, Contribution, Goal, LedgerEntry, Person, RecurringTransaction,
    SavedView, Tag, Transaction, Transfer,
)

MAX_BODY = 64 * 1024
MAX_BULK = 500


class ApiError(Exception):
    def __init__(self, message, status=400, errors=None):
        super().__init__(message)
        self.message, self.status, self.errors = message, status, errors or {}


def error_response(message, status, errors=None):
    return JsonResponse({"ok": False, "message": message, "errors": errors or {}}, status=status)


def form_errors(form):
    """{field: [messages]} with non-field errors under "__all__"."""
    return {field: [e["message"] for e in errs] for field, errs in form.errors.get_json_data().items()}


def api(*methods):
    """Method restriction + authentication + uniform JSON errors."""
    allowed = {m.upper() for m in methods}

    def decorator(view):
        @wraps(view)
        @never_cache
        def wrapper(request, *args, **kwargs):
            if request.method not in allowed:
                response = error_response("Method not allowed.", 405)
                response["Allow"] = ", ".join(sorted(allowed))
                return response
            if not request.user.is_authenticated:
                return error_response("Authentication required.", 401)
            try:
                return view(request, *args, **kwargs)
            except ApiError as exc:
                return error_response(exc.message, exc.status, exc.errors)
            except Http404:
                return error_response("Not found.", 404)
            except ValidationError as exc:
                return error_response(" ".join(exc.messages), 422, {"__all__": exc.messages})

        return wrapper

    return decorator


def body(request):
    """Request payload as a plain dict (JSON or form encoded)."""
    if request.content_type == "application/json":
        if len(request.body) > MAX_BODY:
            raise ApiError("Request body is too large.", 413)
        try:
            data = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise ApiError("Request body is not valid JSON.") from None
        if not isinstance(data, dict):
            raise ApiError("Request body must be a JSON object.")
        return data
    return request.POST


def invalid(form):
    return error_response("Please correct the highlighted fields.", 422, form_errors(form))


def dec(value):
    return f"{value:.2f}"




def tx_json(t):
    return {
        "id": t.pk, "name": t.name, "amount": dec(t.amount), "kind": t.kind, "date": t.date.isoformat(),
        "category": {"id": t.category_id, "name": t.category.name, "color": t.category.color, "icon": t.category.icon},
        "account": {"id": t.account_id, "name": t.account.name} if t.account_id else None,
        "payee": t.payee, "tags": [tag.name for tag in t.tags.all()],
        "note": t.note, "recurring": t.recurring_id is not None,
        "split": t.split_group is not None, "reconciled": t.reconciled,
    }


def cat_json(c):
    data = {"id": c.pk, "name": c.name, "kind": c.kind, "color": c.color, "icon": c.icon,
            "parent": c.parent_id, "full_name": c.full_name}
    if "count" in c.__dict__:
        data["count"] = c.count
    return data


def account_json(a, balance):
    return {"id": a.pk, "name": a.name, "type": a.type, "icon": a.icon, "archived": a.archived,
            "opening_balance": dec(a.opening_balance), "balance": dec(balance)}


def recurring_json(r):
    return {
        "id": r.pk, "name": r.name, "amount": dec(r.amount), "kind": r.kind, "note": r.note, "payee": r.payee,
        "category": {"id": r.category_id, "name": r.category.name, "color": r.category.color, "icon": r.category.icon},
        "account": r.account_id, "frequency": r.frequency, "start_date": r.start_date.isoformat(),
        "end_date": r.end_date.isoformat() if r.end_date else None, "next_due": r.next_due.isoformat(),
        "active": r.active, "last_error": r.last_error,
    }


def owned(model, request, pk, manager=None):
    try:
        return (manager or model.objects).get(pk=pk, user=request.user)
    except model.DoesNotExist:
        raise Http404 from None


def owned_transaction(request, pk, include_deleted=False):
    manager = Transaction.all_objects if include_deleted else Transaction.objects
    try:
        return manager.select_related("category", "account").prefetch_related("tags").get(pk=pk, user=request.user)
    except Transaction.DoesNotExist:
        raise Http404 from None


def after_write(user):
    balance = services.balance_for(user)
    data = {"balance": dec(balance)}
    if balance < 0:
        data["warning"] = "Your balance is below zero."
    return data


def reassign_error(field, message, status=422):
    return ApiError(message, status, {field: [message]})


# --- transactions ------------------------------------------------------------

@api("GET", "POST")
def transactions(request):
    if request.method == "POST":
        form = TransactionForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        tx = services.save_transaction(form.save(commit=False), tags=form.tag_names)
        tx = owned_transaction(request, tx.pk)
        return JsonResponse({"ok": True, "transaction": tx_json(tx), **after_write(request.user)}, status=201)

    flt = TransactionFilter(request.user, request.GET)
    qs = flt.queryset()
    paginator = Paginator(qs, flt.page_size)
    page = paginator.get_page(flt.page)
    income, expense = services.income_expense_for(qs)
    return JsonResponse({
        "ok": True, "transactions": [tx_json(t) for t in page],
        "page": page.number, "pages": paginator.num_pages, "count": paginator.count, "page_size": flt.page_size,
        "totals": {"income": dec(income), "expense": dec(expense)},
    })


@api("GET", "POST", "DELETE")
def transaction_detail(request, pk):
    tx = owned_transaction(request, pk)
    if request.method == "GET":
        return JsonResponse({"ok": True, "transaction": tx_json(tx)})
    if request.method == "DELETE":
        services.delete_transactions(request.user, Transaction.objects.filter(pk=tx.pk))
        return JsonResponse({"ok": True, "id": tx.pk, **after_write(request.user)})
    data = body(request)
    if "tags" not in data:
        data = {**data, "tags": [t.name for t in tx.tags.all()]} if isinstance(data, dict) else data
    form = TransactionForm(data, user=request.user, instance=tx)
    if not form.is_valid():
        return invalid(form)
    tx = services.save_transaction(form.save(commit=False), tags=form.tag_names)
    tx = owned_transaction(request, tx.pk)
    return JsonResponse({"ok": True, "transaction": tx_json(tx), **after_write(request.user)})


@api("POST")
def transaction_restore(request, pk):
    tx = owned_transaction(request, pk, include_deleted=True)
    services.restore_transactions(request.user, [tx.pk])
    tx = owned_transaction(request, pk)
    return JsonResponse({"ok": True, "transaction": tx_json(tx), **after_write(request.user)})


@api("POST")
def transactions_bulk(request):
    data = body(request)
    action = data.get("action")
    ids = data.get("ids")
    if action not in ("delete", "restore", "category", "reconcile", "unreconcile"):
        raise ApiError("Unknown action.", errors={"action": ["Choose delete, restore, category, reconcile or unreconcile."]})
    if not isinstance(ids, list) or not ids or len(ids) > MAX_BULK:
        raise ApiError(f"Select between 1 and {MAX_BULK} transactions.")
    try:
        ids = sorted({int(i) for i in ids})
    except (TypeError, ValueError):
        raise ApiError("Transaction ids must be numbers.") from None
    if Transaction.all_objects.filter(user=request.user, pk__in=ids).count() != len(ids):
        raise Http404
    if action == "delete":
        services.delete_transactions(request.user, Transaction.objects.filter(pk__in=ids))
    elif action == "restore":
        services.restore_transactions(request.user, ids)
    elif action in ("reconcile", "unreconcile"):
        services.set_reconciled(request.user, ids, action == "reconcile")
    else:
        try:
            category = Category.objects.get(pk=int(data.get("category")), user=request.user)
        except (Category.DoesNotExist, TypeError, ValueError):
            raise reassign_error("category", "Choose one of your own categories.") from None
        kinds = set(Transaction.objects.filter(pk__in=ids).values_list("kind", flat=True))
        bad = [k for k in kinds if not category.accepts(k)]
        if bad:
            raise reassign_error("category", f"This category cannot be used for {bad[0]} transactions.")
        services.change_category(request.user, ids, category)
    return JsonResponse({"ok": True, "ids": ids, **after_write(request.user)})


@api("POST")
def transaction_split(request):
    form = SplitForm(body(request), user=request.user)
    if not form.is_valid():
        return invalid(form)
    base = form.base_transaction()
    made = services.create_split(request.user, base, form.parts(), tags=form.cleaned_data["tags"])
    rows = [owned_transaction(request, t.pk) for t in made]
    return JsonResponse({"ok": True, "transactions": [tx_json(t) for t in rows], **after_write(request.user)}, status=201)


def audit_json(e):
    return {"id": e.pk, "transaction": e.transaction_id, "action": e.action, "summary": e.summary,
            "when": e.created_at.isoformat(), "before": e.before, "after": e.after}


@api("GET")
def transaction_history(request, pk):
    tx = owned_transaction(request, pk, include_deleted=True)
    entries = AuditEntry.objects.filter(user=request.user, transaction_id=tx.pk)[:50]
    return JsonResponse({"ok": True, "entries": [audit_json(e) for e in entries]})


@api("GET")
def activity(request):
    entries = AuditEntry.objects.filter(user=request.user)[:40]
    return JsonResponse({"ok": True, "entries": [audit_json(e) for e in entries]})


@api("GET")
def trash(request):
    rows = (Transaction.all_objects.filter(user=request.user, deleted_at__isnull=False)
            .select_related("category", "account").prefetch_related("tags").order_by("-deleted_at"))
    now = timezone.now()
    items = []
    for t in rows:
        data = tx_json(t)
        remaining = services.TRASH_DAYS - (now - t.deleted_at).days
        data.update(deleted_at=t.deleted_at.isoformat(), days_left=max(0, remaining))
        items.append(data)
    return JsonResponse({"ok": True, "transactions": items, "days": services.TRASH_DAYS})


@api("DELETE")
def trash_item(request, pk):
    try:
        tx = Transaction.all_objects.get(pk=pk, user=request.user, deleted_at__isnull=False)
    except Transaction.DoesNotExist:
        raise Http404 from None
    tx.delete()
    return JsonResponse({"ok": True, "id": pk})


@api("POST")
def trash_empty(request):
    count, _ = Transaction.all_objects.filter(user=request.user, deleted_at__isnull=False).delete()
    return JsonResponse({"ok": True, "removed": count})


@api("GET")
def reconcile(request):
    """Cleared balance of an account (opening balance plus reconciled items) for statement matching."""
    try:
        account = Account.objects.get(pk=int(request.GET.get("account", "")), user=request.user)
    except (Account.DoesNotExist, ValueError):
        raise Http404 from None
    cleared = account.opening_balance
    for t in Transaction.objects.filter(user=request.user, account=account, reconciled=True):
        cleared += t.effect
    from django.db.models import Sum
    cleared += (Transfer.objects.filter(user=request.user, to_account=account).aggregate(t=Sum("amount"))["t"] or services.ZERO)
    cleared -= (Transfer.objects.filter(user=request.user, from_account=account).aggregate(t=Sum("amount"))["t"] or services.ZERO)
    pending = Transaction.objects.filter(user=request.user, account=account, reconciled=False).count()
    return JsonResponse({"ok": True, "account": account.pk, "cleared": dec(services.q2(cleared)), "unreconciled": pending,
                         "balance": dec(services.account_balance(account))})


# --- categories --------------------------------------------------------------

def category_queryset(user):
    return Category.objects.filter(user=user).select_related("parent").annotate(
        count=Count("transactions", filter=Q(transactions__deleted_at__isnull=True))
    )


def owned_category(request, pk):
    try:
        return category_queryset(request.user).get(pk=pk)
    except Category.DoesNotExist:
        raise Http404 from None


@api("GET", "POST")
def categories(request):
    if request.method == "POST":
        form = CategoryForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        cat = form.save()
        return JsonResponse({"ok": True, "category": cat_json(owned_category(request, cat.pk))}, status=201)
    return JsonResponse({"ok": True, "categories": [cat_json(c) for c in category_queryset(request.user)]})


@api("GET", "POST", "DELETE")
def category_detail(request, pk):
    cat = owned_category(request, pk)
    if request.method == "GET":
        return JsonResponse({"ok": True, "category": cat_json(cat)})
    if request.method == "POST":
        form = CategoryForm(body(request), user=request.user, instance=cat)
        if not form.is_valid():
            return invalid(form)
        form.save()
        return JsonResponse({"ok": True, "category": cat_json(owned_category(request, pk))})

    in_use = cat.count + cat.recurring.count()
    target = None
    if in_use:
        raw = request.GET.get("reassign_to")
        if not raw:
            raise ApiError(
                f"“{cat.name}” is used by {in_use} item(s). Choose a category to move them to.",
                409, {"reassign_to": ["Required because the category is in use."]})
        try:
            target = Category.objects.get(pk=int(raw), user=request.user)
        except (Category.DoesNotExist, ValueError):
            raise reassign_error("reassign_to", "Choose one of your own categories.") from None
        if target.pk == cat.pk:
            raise reassign_error("reassign_to", "Choose a different category.")
        used_kinds = set(Transaction.objects.filter(category=cat).values_list("kind", flat=True))
        used_kinds |= set(cat.recurring.values_list("kind", flat=True))
        bad = [k for k in used_kinds if not target.accepts(k)]
        if bad:
            raise reassign_error("reassign_to", f"This category cannot be used for {bad[0]} transactions.")
    with services.locked(request.user):
        if target:
            Transaction.all_objects.filter(category=cat).update(category=target)
            cat.recurring.update(category=target)
            Goal.objects.filter(category=cat).update(category=target)
        Transaction.all_objects.filter(category=cat).delete()
        cat.delete()
    return JsonResponse({"ok": True, "id": pk})


# --- accounts and transfers --------------------------------------------------

@api("GET", "POST")
def accounts(request):
    if request.method == "POST":
        form = AccountForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        acct = form.save()
        return JsonResponse({"ok": True, "account": account_json(acct, acct.opening_balance)}, status=201)
    balances = services.account_balances(request.user)
    rows = [account_json(a, balances[a.pk]) for a in Account.objects.filter(user=request.user)]
    total = sum((Decimal(r["balance"]) for r in rows), services.ZERO)
    return JsonResponse({"ok": True, "accounts": rows, "total": dec(total)})


@api("GET", "POST", "DELETE")
def account_detail(request, pk):
    acct = owned(Account, request, pk)
    balances = services.account_balances(request.user)
    if request.method == "GET":
        return JsonResponse({"ok": True, "account": account_json(acct, balances[acct.pk])})
    if request.method == "POST":
        form = AccountForm(body(request), user=request.user, instance=acct)
        if not form.is_valid():
            return invalid(form)
        acct = form.save()
        return JsonResponse({"ok": True, "account": account_json(acct, services.account_balance(acct))})
    busy = (Transaction.all_objects.filter(account=acct).exists() or Transfer.objects.filter(
        Q(from_account=acct) | Q(to_account=acct)).exists() or acct.recurring.exists())
    if busy:
        raise ApiError("This account has activity. Archive it instead of deleting it.", 409)
    if Account.objects.filter(user=request.user).count() == 1:
        raise ApiError("You need at least one account.", 409)
    acct.delete()
    return JsonResponse({"ok": True, "id": pk})


def transfer_json(t):
    return {"id": t.pk, "from": {"id": t.from_account_id, "name": t.from_account.name},
            "to": {"id": t.to_account_id, "name": t.to_account.name}, "amount": dec(t.amount),
            "date": t.date.isoformat(), "note": t.note}


@api("GET", "POST")
def transfers(request):
    if request.method == "POST":
        form = TransferForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        transfer = services.create_transfer(form.save(commit=False))
        transfer = Transfer.objects.select_related("from_account", "to_account").get(pk=transfer.pk)
        return JsonResponse({"ok": True, "transfer": transfer_json(transfer)}, status=201)
    rows = Transfer.objects.filter(user=request.user).select_related("from_account", "to_account")[:50]
    return JsonResponse({"ok": True, "transfers": [transfer_json(t) for t in rows]})


@api("DELETE")
def transfer_detail(request, pk):
    transfer = owned(Transfer, request, pk)
    services.delete_transfer(transfer)
    return JsonResponse({"ok": True, "id": pk})


# --- tags, rules, payees -----------------------------------------------------

@api("GET")
def tags(request):
    rows = Tag.objects.filter(user=request.user).annotate(
        count=Count("transactions", filter=Q(transactions__deleted_at__isnull=True)))
    return JsonResponse({"ok": True, "tags": [{"id": t.pk, "name": t.name, "count": t.count} for t in rows]})


@api("POST", "DELETE")
def tag_detail(request, pk):
    tag = owned(Tag, request, pk)
    if request.method == "DELETE":
        tag.delete()
        return JsonResponse({"ok": True, "id": pk})
    name = " ".join(str(body(request).get("name", "")).split())
    if not name or len(name) > 30:
        raise ApiError("Enter a name of up to 30 characters.", 422, {"name": ["Enter a name of up to 30 characters."]})
    if Tag.objects.filter(user=request.user, name__iexact=name).exclude(pk=pk).exists():
        raise ApiError("You already have a tag with that name.", 422, {"name": ["You already have a tag with that name."]})
    tag.name = name
    tag.save(update_fields=["name"])
    return JsonResponse({"ok": True, "tag": {"id": tag.pk, "name": tag.name}})


def rule_json(r):
    return {"id": r.pk, "pattern": r.pattern, "priority": r.priority, "active": r.active,
            "category": {"id": r.category_id, "name": r.category.name, "color": r.category.color}}


@api("GET", "POST")
def rules(request):
    if request.method == "POST":
        form = RuleForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        rule = form.save()
        return JsonResponse({"ok": True, "rule": rule_json(rule)}, status=201)
    rows = CategoryRule.objects.filter(user=request.user).select_related("category")
    return JsonResponse({"ok": True, "rules": [rule_json(r) for r in rows]})


@api("POST", "DELETE")
def rule_detail(request, pk):
    rule = owned(CategoryRule, request, pk)
    if request.method == "DELETE":
        rule.delete()
        return JsonResponse({"ok": True, "id": pk})
    form = RuleForm(body(request), user=request.user, instance=rule)
    if not form.is_valid():
        return invalid(form)
    return JsonResponse({"ok": True, "rule": rule_json(form.save())})


@api("GET")
def rule_suggest(request):
    kind = request.GET.get("kind")
    cat = services.suggest_category(request.user, request.GET.get("text", ""), kind if kind in ("income", "expense") else None)
    return JsonResponse({"ok": True, "category": cat_json(cat) if cat else None})


@api("GET")
def suggest(request):
    q = (request.GET.get("q") or "").strip()[:50]
    kind = request.GET.get("type")
    if kind == "tag":
        qs = Tag.objects.filter(user=request.user, name__icontains=q).values_list("name", flat=True)[:8]
        return JsonResponse({"ok": True, "items": list(qs)})
    if kind == "payee":
        rows = (Transaction.objects.filter(user=request.user, payee__icontains=q).exclude(payee="")
                .values("payee").annotate(c=Count("id")).order_by("-c", "payee")[:8])
        return JsonResponse({"ok": True, "items": [r["payee"] for r in rows]})
    raise ApiError("type must be payee or tag.")


# --- saved views -------------------------------------------------------------

@api("GET", "POST")
def saved_views(request):
    if request.method == "POST":
        form = SavedViewForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        form.save()
    rows = SavedView.objects.filter(user=request.user)
    return JsonResponse({"ok": True, "views": [{"id": v.pk, "name": v.name, "query": v.query} for v in rows]},
                        status=201 if request.method == "POST" else 200)


@api("DELETE")
def saved_view_detail(request, pk):
    owned(SavedView, request, pk).delete()
    return JsonResponse({"ok": True, "id": pk})


# --- budgets -----------------------------------------------------------------

def budget_json(item):
    out = dict(item)
    for key in ("limit", "carry", "available", "spent", "remaining", "projected", "safe_per_day"):
        out[key] = dec(out[key])
    out["weekly"] = [dec(x) for x in out["weekly"]]
    out["weekly_limit"] = [dec(x) for x in out["weekly_limit"]]
    return out


def budget_payload(user, month):
    data = budgeting.status(user, month)
    totals = {k: (dec(v) if isinstance(v, Decimal) else v) for k, v in data["totals"].items()}
    return {
        "ok": True, "month": data["month"].strftime("%Y-%m"),
        "overall": budget_json(data["overall"]) if data["overall"] else None,
        "budgets": [budget_json(i) for i in data["categories"]],
        "weeks": [{"start": w["start"], "end": w["end"]} for w in data["weeks"]],
        "totals": totals,
        "has_previous": Budget.objects.filter(user=user, month=services.add_months(data["month"], -1)).exists(),
    }


@api("GET", "POST")
def budgets(request):
    month = services.parse_month(request.GET.get("month"))
    if request.method == "POST":
        form = BudgetForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        form.save()
        month = form.cleaned_data["month"]
    return JsonResponse(budget_payload(request.user, month), status=201 if request.method == "POST" else 200)


@api("DELETE")
def budget_detail(request, pk):
    owned(Budget, request, pk).delete()
    return JsonResponse({"ok": True, "id": pk})


@api("POST")
def budget_copy(request):
    data = body(request)
    source = services.parse_month(data.get("from"), default=None) if data.get("from") else None
    target = services.parse_month(data.get("to"), default=None) if data.get("to") else None
    if source is None or target is None or source == target:
        raise ApiError("Choose two different months like 2025-03.")
    created = budgeting.copy_month(request.user, source, target)
    return JsonResponse({**budget_payload(request.user, target), "copied": created})


@api("GET")
def budget_history(request):
    try:
        months = max(1, min(24, int(request.GET.get("months", 12))))
    except ValueError:
        months = 12
    rows = budgeting.history(request.user, months)
    for r in rows:
        r["limit"] = dec(r["limit"]) if r["limit"] is not None else None
        r["spent"] = dec(r["spent"])
    return JsonResponse({"ok": True, "months": rows})


# --- goals -------------------------------------------------------------------

def goal_json(goal):
    info = budgeting.goal_summary(goal)
    return {
        "id": goal.pk, "name": goal.name, "target_amount": dec(goal.target_amount),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "account": {"id": goal.account_id, "name": goal.account.name} if goal.account_id else None,
        "category": {"id": goal.category_id, "name": goal.category.name} if goal.category_id else None,
        "saved": dec(info["saved"]), "remaining": dec(info["remaining"]), "percent": info["percent"],
        "required_monthly": dec(info["required_monthly"]) if info["required_monthly"] is not None else None,
        "months_left": info["months_left"], "complete": info["complete"], "overdue": info["overdue"],
        "contributions": [{"id": c.pk, "amount": dec(c.amount), "date": c.date.isoformat(), "note": c.note}
                          for c in goal.contributions.all()[:20]],
    }


def goal_queryset(user):
    return Goal.objects.filter(user=user).select_related("account", "category").prefetch_related("contributions")


@api("GET", "POST")
def goals(request):
    if request.method == "POST":
        form = GoalForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        goal = form.save()
        return JsonResponse({"ok": True, "goal": goal_json(goal_queryset(request.user).get(pk=goal.pk))}, status=201)
    return JsonResponse({"ok": True, "goals": [goal_json(g) for g in goal_queryset(request.user)]})


@api("GET", "POST", "DELETE")
def goal_detail(request, pk):
    goal = owned(Goal, request, pk, goal_queryset(request.user))
    if request.method == "GET":
        return JsonResponse({"ok": True, "goal": goal_json(goal)})
    if request.method == "DELETE":
        goal.delete()
        return JsonResponse({"ok": True, "id": pk})
    form = GoalForm(body(request), user=request.user, instance=goal)
    if not form.is_valid():
        return invalid(form)
    form.save()
    return JsonResponse({"ok": True, "goal": goal_json(goal_queryset(request.user).get(pk=pk))})


@api("POST")
def goal_contribute(request, pk):
    goal = owned(Goal, request, pk, goal_queryset(request.user))
    form = ContributionForm(body(request))
    if not form.is_valid():
        return invalid(form)
    contribution = form.save(commit=False)
    saved = budgeting.goal_summary(goal)["saved"]
    if saved + contribution.amount < 0:
        raise ApiError("A goal cannot have a negative amount saved.", 422,
                       {"amount": ["A goal cannot have a negative amount saved."]})
    contribution.goal = goal
    contribution.save()
    return JsonResponse({"ok": True, "goal": goal_json(goal_queryset(request.user).get(pk=pk))}, status=201)


@api("DELETE")
def contribution_detail(request, pk):
    try:
        item = Contribution.objects.select_related("goal").get(pk=pk, goal__user=request.user)
    except Contribution.DoesNotExist:
        raise Http404 from None
    item.delete()
    return JsonResponse({"ok": True, "id": pk})


# --- recurring ---------------------------------------------------------------

def owned_recurring(request, pk):
    try:
        return RecurringTransaction.objects.select_related("category").get(pk=pk, user=request.user)
    except RecurringTransaction.DoesNotExist:
        raise Http404 from None


@api("GET", "POST")
def recurring(request):
    if request.method == "POST":
        form = RecurringForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        item = form.save()
        services.apply_due(request.user)
        item.refresh_from_db()
        return JsonResponse({"ok": True, "item": recurring_json(item)}, status=201)
    items = RecurringTransaction.objects.filter(user=request.user).select_related("category")
    return JsonResponse({"ok": True, "items": [recurring_json(i) for i in items]})


@api("GET", "POST", "DELETE")
def recurring_detail(request, pk):
    item = owned_recurring(request, pk)
    if request.method == "GET":
        return JsonResponse({"ok": True, "item": recurring_json(item)})
    if request.method == "DELETE":
        item.delete()
        return JsonResponse({"ok": True, "id": pk})
    form = RecurringForm(body(request), user=request.user, instance=item)
    if not form.is_valid():
        return invalid(form)
    item = form.save()
    return JsonResponse({"ok": True, "item": recurring_json(item)})


@api("POST")
def recurring_toggle(request, pk):
    item = owned_recurring(request, pk)
    item.active = not item.active
    if item.active:
        # resuming skips occurrences missed while paused
        item.next_due = services.first_due_on_or_after(item, max(item.next_due, timezone.localdate()))
        if item.end_date and item.next_due > item.end_date:
            item.active = False
    item.last_error = ""
    item.save(update_fields=["active", "next_due", "last_error"])
    return JsonResponse({"ok": True, "item": recurring_json(item)})


# --- people: debts and shared bills --------------------------------------------

def person_json(p, entries=False):
    rows = list(p.entries.all())
    net = sum((e.amount for e in rows), services.ZERO)
    due = [e.due_date for e in rows if e.due_date and e.kind in ("lent", "borrowed")]
    data = {"id": p.pk, "name": p.name, "net": dec(net),
            "direction": "owes_you" if net > 0 else "you_owe" if net < 0 else "settled",
            "next_due": min(due).isoformat() if due and net != 0 else None}
    if entries:
        data["entries"] = [{"id": e.pk, "kind": e.kind, "kind_label": e.get_kind_display(), "amount": dec(e.amount),
                            "description": e.description, "date": e.date.isoformat(),
                            "due_date": e.due_date.isoformat() if e.due_date else None} for e in rows]
    return data


@api("GET", "POST")
def people(request):
    if request.method == "POST":
        form = PersonForm(body(request), user=request.user)
        if not form.is_valid():
            return invalid(form)
        person = form.save()
        return JsonResponse({"ok": True, "person": person_json(person)}, status=201)
    rows = Person.objects.filter(user=request.user).prefetch_related("entries")
    items = [person_json(p, entries=True) for p in rows]
    owed = sum((Decimal(i["net"]) for i in items if Decimal(i["net"]) > 0), services.ZERO)
    owe = sum((-Decimal(i["net"]) for i in items if Decimal(i["net"]) < 0), services.ZERO)
    return JsonResponse({"ok": True, "people": items, "owed_to_you": dec(owed), "you_owe": dec(owe)})


@api("POST", "DELETE")
def person_detail(request, pk):
    person = owned(Person, request, pk)
    if request.method == "DELETE":
        person.delete()
        return JsonResponse({"ok": True, "id": pk})
    form = PersonForm(body(request), user=request.user, instance=person)
    if not form.is_valid():
        return invalid(form)
    return JsonResponse({"ok": True, "person": person_json(form.save())})


@api("POST")
def person_entry(request, pk):
    person = owned(Person, request, pk)
    form = LedgerEntryForm(body(request))
    if not form.is_valid():
        return invalid(form)
    entry = form.build(person)
    entry.save()
    person = Person.objects.prefetch_related("entries").get(pk=pk)
    return JsonResponse({"ok": True, "person": person_json(person, entries=True)}, status=201)


@api("DELETE")
def entry_detail(request, pk):
    try:
        entry = LedgerEntry.objects.get(pk=pk, person__user=request.user)
    except LedgerEntry.DoesNotExist:
        raise Http404 from None
    entry.delete()
    return JsonResponse({"ok": True, "id": pk})


# --- reports, search, status -------------------------------------------------

def _iso_date(value, default):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@api("GET")
def summary(request):
    month = services.parse_month(request.GET.get("month"))
    data = stats.summary(request.user, month)
    profile = services.get_profile(request.user)
    return JsonResponse({"ok": True, **_jsonable(data), "overdrawn": data["balance"] < 0,
                         "allow_negative": services.allows_negative(request.user),
                         "currency": profile.currency_code,
                         "secondary": {"code": profile.secondary_currency_code,
                                       "rate": str(profile.secondary_rate) if profile.secondary_rate else None}})


@api("GET")
def analytics(request):
    today = timezone.localdate()
    start = _iso_date(request.GET.get("start"), services.month_start(today))
    end = _iso_date(request.GET.get("end"), today)
    if start < datetime.date(2000, 1, 1) or end > today + datetime.timedelta(days=366):
        raise ApiError("Date range is out of bounds.", 422)
    category = _int(request.GET.get("category"))
    tag = _int(request.GET.get("tag"))
    if category and not Category.objects.filter(pk=category, user=request.user).exists():
        raise Http404
    if tag and not Tag.objects.filter(pk=tag, user=request.user).exists():
        raise Http404
    return JsonResponse({"ok": True, **_jsonable(stats.analytics(request.user, start, end, category, tag, today))})


@api("GET")
def insights(request):
    data = insight_lib.insights(request.user)
    profile = services.get_profile(request.user)
    return JsonResponse({"ok": True, **_jsonable(data), "secondary": {
        "code": profile.secondary_currency_code,
        "rate": str(profile.secondary_rate) if profile.secondary_rate else None}})


@api("GET")
def notifications(request):
    items = budgeting.notifications(request.user)
    return JsonResponse({"ok": True, "notifications": items, "count": len(items)})


@api("GET")
def search(request):
    q = " ".join((request.GET.get("q") or "").split())[:60]
    if len(q) < 2:
        return JsonResponse({"ok": True, "q": q, "groups": []})
    user = request.user
    profile = services.get_profile(user)
    groups = []
    params, parts = nlq.parse(
        q, [{"id": c.pk, "name": c.full_name} for c in Category.objects.filter(user=user).select_related("parent")],
        list(Account.objects.filter(user=user).values("id", "name")),
        list(Tag.objects.filter(user=user).values("id", "name")), timezone.localdate())
    structured = {k for k in params if k != "q"}
    if structured:
        groups.append({"type": "Filter transactions", "items": [{
            "title": "Show " + ", ".join(parts), "subtitle": "Open these filters on the Transactions page",
            "url": "/transactions/?" + urlencode(params)}]})
    txs = (Transaction.objects.filter(user=user).filter(Q(name__icontains=q) | Q(payee__icontains=q) | Q(note__icontains=q))
           .select_related("category")[:5])
    if txs:
        groups.append({"type": "Transactions", "items": [{
            "title": t.name, "subtitle": f"{t.date:%Y-%m-%d} · {t.category.name} · "
            f"{'+' if t.kind == 'income' else '-'}{format_money(t.amount, profile)}",
            "url": "/transactions/?" + urlencode({"q": t.name})} for t in txs]})
    payees = (Transaction.objects.filter(user=user, payee__icontains=q).exclude(payee="")
              .values("payee").annotate(c=Count("id")).order_by("-c")[:5])
    if payees:
        groups.append({"type": "Payees", "items": [{"title": p["payee"], "subtitle": f"{p['c']} transaction(s)",
                                                    "url": "/transactions/?" + urlencode({"payee": p["payee"]})} for p in payees]})
    cats = Category.objects.filter(user=user, name__icontains=q)[:5]
    if cats:
        groups.append({"type": "Categories", "items": [{"title": c.name, "subtitle": c.get_kind_display(),
                                                        "url": f"/transactions/?category={c.pk}"} for c in cats]})
    tag_rows = Tag.objects.filter(user=user, name__icontains=q)[:5]
    if tag_rows:
        groups.append({"type": "Tags", "items": [{"title": t.name, "subtitle": "Tag", "url": f"/transactions/?tag={t.pk}"}
                                                 for t in tag_rows]})
    acct_rows = Account.objects.filter(user=user, name__icontains=q)[:5]
    if acct_rows:
        groups.append({"type": "Accounts", "items": [{"title": a.name, "subtitle": a.get_type_display(),
                                                      "url": f"/transactions/?account={a.pk}"} for a in acct_rows]})
    goal_rows = Goal.objects.filter(user=user, name__icontains=q)[:5]
    if goal_rows:
        groups.append({"type": "Goals", "items": [{"title": g.name, "subtitle": f"Target {format_money(g.target_amount, profile)}",
                                                   "url": "/goals/"} for g in goal_rows]})
    return JsonResponse({"ok": True, "q": q, "groups": groups})


def onboarding_state(user):
    has_custom = Category.objects.filter(user=user).exclude(name__in=[c[0] for c in services.DEFAULT_CATEGORIES]).exists()
    steps = [
        {"id": "category", "label": "Add a category of your own", "done": has_custom, "url": "/categories/"},
        {"id": "transaction", "label": "Record your first transaction", "done": Transaction.objects.filter(user=user).exists(),
         "url": "/transactions/#new"},
        {"id": "budget", "label": "Set a monthly budget", "done": Budget.objects.filter(user=user).exists(), "url": "/budgets/"},
        {"id": "goal", "label": "Create a savings goal", "done": Goal.objects.filter(user=user).exists(), "url": "/goals/"},
    ]
    profile = services.get_profile(user)
    complete = all(s["done"] for s in steps)
    return {"steps": steps, "dismissed": profile.onboarding_dismissed or complete,
            "can_load_sample": not Transaction.all_objects.filter(user=user).exists()}


@api("GET", "POST")
def onboarding(request):
    if request.method == "POST":
        profile = services.get_profile(request.user)
        profile.onboarding_dismissed = True
        profile.save(update_fields=["onboarding_dismissed"])
        services.forget_profile(request.user)
    return JsonResponse({"ok": True, **onboarding_state(request.user)})


@api("POST")
def sample_data(request):
    if Transaction.all_objects.filter(user=request.user).exists():
        raise ApiError("Sample data can only be added to an empty account.", 409)
    demo.seed_user(request.user)
    return JsonResponse({"ok": True, **onboarding_state(request.user)}, status=201)


def _jsonable(value):
    if isinstance(value, Decimal):
        return dec(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value
