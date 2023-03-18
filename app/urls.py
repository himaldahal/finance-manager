from django.urls import path
from .views import *


urlpatterns = [
    path('translist/', transaction_list, name='transaction_list'),
    path('', TransactionListView.as_view(), name='home'),
    path('balance/',getBalace,name="balance"),
    path('analysis/',dataVisualizer,name="graph-analyis"),
    path('create/', TransactionCreateView.as_view(), name='transaction_create'),
    path('<int:pk>/update/', TransactionUpdateView.as_view(), name='transaction_update'),
    path('<int:transaction_id>/delete/', delete_transaction, name='transaction_delete'),
    path('expense-summary/', expense_summary, name='expense_summary'),

]
