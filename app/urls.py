from django.urls import path
from .views import *


urlpatterns = [
    path('translist/', transaction_list, name='transaction_list'),
    path('', TransactionListView.as_view(), name='home'),
   
    path('graph/',analysis,name="graph"),
    path('create/', transaction_create_view, name='transaction_create'),
    path('transaction_type_create/',create_transaction_type,name='transaction_type_create'),
    path('<int:pk>/update/', TransactionUpdateView.as_view(), name='transaction_update'),
    path('<int:transaction_id>/delete/', delete_transaction, name='transaction_delete'),
    path('currency/',c_ex,name="currency_exchange"),

    # apis
    path('summary/',transaction_summary,name="transaction_summary"),
    path('analysis/',category_wise_expenses,name="category_wise_expenses"),
    path('balance/',getBalace,name="balance"),
    path('expense-summary/', expense_summary, name='expense_summary'),

    # login view
    path('login/', CustomLoginView.as_view(), name='login'),
    path('register/',register,name="register"),


]


