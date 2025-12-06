from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.html import escape
from django.views.generic import ListView, UpdateView

from .forms import (AccountForm, CategoryForm, RegisterForm, TransactionForm,
                    TransactionUpdateForm)
from .models import Account, Category, Transaction
from .services import TransactionService


class CustomLoginView(LoginView):
    template_name = "registration/login.html"


def create_category(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            name = escape(form.cleaned_data["name"])
            if Category.objects.filter(name__iexact=name, user=request.user).exists():
                return JsonResponse(
                    {"error": f"A category with name '{name}' already exists."}
                )
            else:
                category = form.save(commit=False)
                category.user = request.user
                category.name = name
                category.save()
                return JsonResponse(
                    {"success": f"Category '{name}' added successfully!"}
                )
        else:
            return JsonResponse({"success": False, "errors": form.errors.as_json()})
    else:
        form = CategoryForm()
    return render(request, "category_create.html", {"form": form})


def create_account(request):
    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            name = escape(form.cleaned_data["name"])
            if Account.objects.filter(name__iexact=name, owner=request.user).exists():
                return JsonResponse(
                    {"error": f"An account with name '{name}' already exists."}
                )
            else:
                account = form.save(commit=False)
                account.owner = request.user
                account.name = name
                account.balance = account.opening_balance
                account.save()
                return JsonResponse(
                    {"success": f"Account '{name}' added successfully!"}
                )
        else:
            return JsonResponse({"success": False, "errors": form.errors.as_json()})
    else:
        form = AccountForm()
    return render(request, "account_create.html", {"form": form})


class TransactionListView(ListView):
    model = Transaction
    template_name = "transaction_list.html"
    context_object_name = "transactions"

    def get_queryset(self):
        return Transaction.objects.filter(user=self.request.user, is_deleted=False)

    def get(self, request, *args, **kwargs):
        if (
            request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
            and request.GET.get("action") == "get_data"
        ):
            transactions = self.get_queryset()
            data = {"transactions": []}
            for transaction in transactions:
                data["transactions"].append(
                    {
                        "name": transaction.name,
                        "amount": str(transaction.amount),
                        "date": str(transaction.date),
                        "type": transaction.get_transaction_type_display(),
                        "category": transaction.category.name
                        if transaction.category
                        else "",
                        "account": transaction.account.name,
                        "remarks": transaction.remarks,
                    }
                )
            return JsonResponse(data, safe=False)

        return super().get(request, *args, **kwargs)


def transaction_create_view(request):
    if request.method == "GET":
        form = TransactionForm(user=request.user)
        return render(request, "transaction_form_modal.html", {"form": form})

    if request.method == "POST":
        form = TransactionForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            payload = form.cleaned_data
            payload["user"] = request.user
            try:
                TransactionService.create_transaction(payload)
                return JsonResponse({"success": True})
            except ValidationError as e:
                return JsonResponse({"success": False, "message": e.message})
        else:
            errors = form.errors.as_json()
            return JsonResponse({"success": False, "errors": errors})


class TransactionUpdateView(UpdateView):
    model = Transaction
    form_class = TransactionUpdateForm
    template_name = "transaction_form.html"
    success_url = reverse_lazy("transaction_list")

    def dispatch(self, request, *args, **kwargs):
        transaction = self.get_object()
        if request.user != transaction.user:
            is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
            if is_ajax:
                # Improved error message for AJAX requests
                return JsonResponse(
                    {
                        "success": False,
                        "errors": "Permission denied. You do not have permission to edit this transaction.",
                    }
                )
            else:
                # Standard HTTP error for non-AJAX requests
                return HttpResponseForbidden(
                    "You do not have permission to edit this transaction."
                )

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        if form.is_valid():
            payload = form.cleaned_data
            try:
                TransactionService.update_transaction(self.get_object(), payload)
                return JsonResponse({"success": True})
            except ValidationError as e:
                return JsonResponse({"success": False, "message": e.message})
        else:
            data = {"success": False, "errors": form.errors}
        return JsonResponse(data)


def delete_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, user=request.user)

    if request.method == "DELETE":
        TransactionService.delete_transaction(transaction)
        return JsonResponse({"success": True})

    return JsonResponse({"success": False, "message": "Transaction not deleted."})


def get_balance(request):
    accounts = Account.objects.filter(owner=request.user)
    total_balance = sum(account.balance for account in accounts)

    data = {
        "balance": f"{total_balance:.2f}",
        "accounts": list(accounts.values("name", "balance")),
    }
    return JsonResponse(data)


def analysis(request):
    return render(request, "trans_analysis.html", {})


def transaction_list(request):
    transactions = Transaction.objects.filter(
        user=request.user, is_deleted=False
    ).values(
        "pk",
        "name",
        "amount",
        "date",
        "transaction_type",
        "category__name",
        "remarks",
    )
    data = {"transactions": list(transactions)}
    return JsonResponse(data)


def expense_summary(request):
    expenses = (
        Transaction.objects.filter(
            transaction_type="expense", user=request.user, is_deleted=False
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("-month")
    )
    data = {"expenses": list(expenses)}
    return JsonResponse(data)


def transaction_summary(request):
    expenses = (
        Transaction.objects.filter(
            transaction_type="expense", user=request.user, is_deleted=False
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("-month")
    )

    income = (
        Transaction.objects.filter(
            transaction_type="income", user=request.user, is_deleted=False
        )
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
        .order_by("-month")
    )

    data = {"expenses": list(expenses), "incomes": list(income)}
    return JsonResponse(data)


def category_wise_expenses(request):
    tsk_model = Transaction.objects.filter(user=request.user, is_deleted=False).values(
        "category__name", "amount"
    )
    return JsonResponse({"data": list(tsk_model)}, safe=False)


def c_ex(request):
    return render(request, "currency_exchange.html")


def register(request):
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            # sanitize user inputs before saving
            user.username = escape(user.username)
            user.email = escape(user.email)
            user.first_name = escape(user.first_name)
            user.last_name = escape(user.last_name)
            user.set_password(form.cleaned_data["password2"])
            user.save()

            messages.success(request, "You have successfully registered!")
            login(request, user)
            Account.objects.create(
                owner=user,
                name="Default Account",
                account_type="bank",
                opening_balance=0,
            )
            return redirect(reverse_lazy("home"))
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = RegisterForm()

    context = {"form": form}
    return render(request, "registration/register.html", context)
