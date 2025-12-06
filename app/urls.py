from django.urls import path

from .views import (CustomLoginView, TransactionListView,
                    TransactionUpdateView, analysis, c_ex,
                    category_wise_expenses, create_account, create_category,
                    delete_transaction, expense_summary, get_balance, register,
                    transaction_create_view, transaction_list,
                    transaction_summary)

urlpatterns = [
    path("translist/", transaction_list, name="transaction_list"),
    path("", TransactionListView.as_view(), name="home"),
    path("graph/", analysis, name="graph"),
    path("create/", transaction_create_view, name="transaction_create"),
    path("category/create/", create_category, name="category_create"),
    path("account/create/", create_account, name="account_create"),
    path(
        "<int:pk>/update/", TransactionUpdateView.as_view(), name="transaction_update"
    ),
    path("<int:transaction_id>/delete/", delete_transaction, name="transaction_delete"),
    path("currency/", c_ex, name="currency_exchange"),
    # apis
    path("summary/", transaction_summary, name="transaction_summary"),
    path("analysis/", category_wise_expenses, name="category_wise_expenses"),
    path("balance/", get_balance, name="balance"),
    path("expense-summary/", expense_summary, name="expense_summary"),
    # login view
    path("login/", CustomLoginView.as_view(), name="login"),
    path("register/", register, name="register"),
]
