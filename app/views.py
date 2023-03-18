from django.shortcuts import render, redirect
from django.views.generic import ListView,CreateView, UpdateView, DeleteView
from django.db.models.functions import TruncMonth
from django.db.models import Sum
from django.urls import reverse_lazy
from .models import Transaction, TransactionType, Balance
from .forms import TransactionForm
from django.core import serializers
from django.shortcuts import get_object_or_404
from django.http import *
from django.views.decorators.csrf import csrf_exempt

class TransactionListView(ListView):
    model = Transaction
    template_name = 'transaction_list.html'
    context_object_name = 'transactions'

    def get(self, request, *args, **kwargs):
        if request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest' and request.GET.get('action') == 'get_data':
            transactions = self.get_queryset()
            data = {
                'transactions': []
            }
            for transaction in transactions:
                data['transactions'].append({
                    'name': transaction.name,
                    'amount': str(transaction.amount),
                    'date': str(transaction.date),
                    'type': transaction.get_transaction_type_display(),
                    'category': transaction.category.name,
                    'remarks': transaction.remarks
                })
            return JsonResponse(data, safe=False)

        return super().get(request, *args, **kwargs)
class TransactionCreateView(CreateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'transaction_form_modal.html'
    success_url = reverse_lazy('transaction_list')
   
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['transaction_form'] = TransactionForm()
        return context

    def form_valid(self, form):
        if form.is_valid():
            response = super().form_valid(form)
            data = {'success': True}
        else:
            data = {'success': False, 'errors': form.errors }

        return JsonResponse(data)

class TransactionUpdateView(UpdateView):
    model = Transaction
    form_class = TransactionForm
    template_name = 'transaction_form.html'
    success_url = reverse_lazy('transaction_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['transaction_form'] = TransactionForm()
        return context

    def form_valid(self, form):
        if form.is_valid():
            response = super().form_valid(form)
            data = {'success': True}

        else:
            data = {'success': False, 'errors': form.errors }

        return JsonResponse(data)

@csrf_exempt
def delete_transaction(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id)
    if request.method == 'DELETE':
        transaction.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'message': 'Invalid Request'})
    
def getBalace(request):
    total_transaction = 0
    trans_object = Transaction.objects.all() 
    for i in trans_object:
        total_transaction += i.amount
    data = { 'balance': str(Balance.objects.filter().first()),'total_transaction':total_transaction }
    return JsonResponse(data)

def dataVisualizer(request):
    tsk_model = Transaction.objects.all().values('category__name', 'amount')
    return JsonResponse({'data': list(tsk_model)}, safe=False)

def transaction_list(request):
    transactions = Transaction.objects.all().values('pk','name','amount','date','transaction_type','category__name','remarks')
    data = {"transactions": list(transactions) }
    return JsonResponse(data)
    
def expense_summary(request):
    expenses = Transaction.objects.filter(transaction_type='expense') \
        .annotate(month=TruncMonth('date')) \
        .values('month') \
        .annotate(total=Sum('amount')) \
        .order_by('-month')
    data = {
        'expenses': list(expenses)
    }
    return JsonResponse(data)