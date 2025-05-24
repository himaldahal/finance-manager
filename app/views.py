from django.views.generic import ListView, UpdateView
from django.shortcuts import render, redirect
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db.models.functions import TruncMonth
from django.template.loader import render_to_string
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.utils.html import escape
from django.urls import reverse_lazy

from django.core import serializers
from django.contrib.auth import login
from django.db.models import Sum
from django.http import *, HttpResponseForbidden
from .models import *
from .forms import *
from django.core.exceptions import ValidationError


class CustomLoginView(LoginView):
    authentication_form = CustomAuthenticationForm
    template_name = 'registration/login.html'

def create_transaction_type(request):
    if request.method == 'POST':
        form = TransactionTypeForm(request.POST)
        if form.is_valid():
            name = escape(form.cleaned_data['name'])
            if TransactionType.objects.filter(name__iexact=name).exists():
                return JsonResponse({'error': f"A transaction type with name '{name}' already exists."})
            else:
                transaction_type = form.save(commit=False)
                transaction_type.added_by = request.user
                transaction_type.name = name
                transaction_type.save()
                return JsonResponse({'success': f"Transaction type '{name}' added successfully!"})
        else:
            return JsonResponse({'success': False, 'errors': form.errors.as_json()})
    else:
        form = TransactionTypeForm()
    return render(request, 'transaction_type_create.html', {'form': form})


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

def transaction_create_view(request):
    if request.method == 'GET':
        form = TransactionForm(user=request.user)
        return render(request,'transaction_form_modal.html', {'form': form})

    if request.method == 'POST':
        form = TransactionForm(request.POST, user=request.user)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.transaction_of = request.user
            try:
                transaction.save() # Model's save method now handles balance
                return JsonResponse({'success': True})
            except ValidationError as e:
                # Assuming e.message contains the error string from the model
                return JsonResponse({'success': False, 'message': e.message if hasattr(e, 'message') else str(e)})
        else:
            errors = form.errors.as_json()
            return JsonResponse({'success': False, 'errors': errors})

class TransactionUpdateView(UpdateView):
    model = Transaction
    form_class = TransactionUpdateForm
    template_name = 'transaction_form.html'
    success_url = reverse_lazy('transaction_list')

    def dispatch(self, request, *args, **kwargs):
        transaction = self.get_object()
        if request.user != transaction.transaction_of:
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            if is_ajax:
                # Improved error message for AJAX requests
                return JsonResponse({'success': False, 'errors': 'Permission denied. You do not have permission to edit this transaction.'})
            else:
                # Standard HTTP error for non-AJAX requests
                return HttpResponseForbidden("You do not have permission to edit this transaction.")

        return super().dispatch(request, *args, **kwargs)
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['transaction_form'] = TransactionUpdateForm()
        return context

    def form_valid(self, form):
        if form.is_valid():
            response = super().form_valid(form)
            data = {'success': True}
        else:
            data = {'success': False, 'errors': form.errors}
        return JsonResponse(data)

def delete_transaction(request, transaction_id):
    transaction = Transaction.objects.filter(id=transaction_id, transaction_of=request.user)
    if transaction.exists() == False:
         return JsonResponse({'success': False, 'message': 'Transaction doesn\'t exists.'})

    if request.method == 'DELETE':
        transaction.delete()
        return JsonResponse({'success': True})
    
    return JsonResponse({'success': False, 'message': 'Transaction not deleted.'})
   
    
def getBalace(request):
    trans_object = Transaction.objects.filter(transaction_of=request.user)
    transaction_amount = sum(trans.amount for trans in trans_object)
    balance_obj = Balance.objects.filter(balance_of=request.user).first()
    current_balance_str = "0.00"
    if balance_obj:
        current_balance_str = f"{balance_obj.balance:.2f}" # Ensure two decimal places formatting

    data = { 
        'balance': current_balance_str, 
        'total_transaction': transaction_amount 
    }
    return JsonResponse(data)


def analysis(request):
    return render(request,'trans_analysis.html',{})

def transaction_list(request):
    transactions = Transaction.objects.filter(transaction_of=request.user) .values('pk','name','amount','date','transaction_type','category__name','remarks')
    data = {"transactions": list(transactions) }
    return JsonResponse(data)
    
def expense_summary(request):
    expenses = Transaction.objects.filter(transaction_type='expense',transaction_of=request.user) \
        .annotate(month=TruncMonth('date')) \
        .values('month') \
        .annotate(total=Sum('amount')) \
        .order_by('-month')
    data = {
        'expenses': list(expenses)
    }
    return JsonResponse(data)

def transaction_summary(request):
    expenses = Transaction.objects.filter(transaction_type='expense',transaction_of=request.user) \
        .annotate(month=TruncMonth('date')) \
        .values('month') \
        .annotate(total=Sum('amount')) \
        .order_by('-month')
        
    income = Transaction.objects.filter(transaction_type='income',transaction_of=request.user) \
        .annotate(month=TruncMonth('date')) \
        .values('month') \
        .annotate(total=Sum('amount')) \
        .order_by('-month')

    data = {
        'expenses': list(expenses),
        'incomes':list(income)
    }
    return JsonResponse(data)  

def category_wise_expenses(request):
    tsk_model = Transaction.objects.filter(transaction_of=request.user) .values('category__name', 'amount')
    return JsonResponse({'data': list(tsk_model)}, safe=False)

def c_ex(request):
    return render(request,'currency_exchange.html')

def register(request):
    if request.method == 'POST':
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

            messages.success(request, 'You have successfully registered!')
            login(request, user)
            balance = Balance.objects.create(balance_of=user,balance="0.00")
            return redirect(reverse_lazy('home'))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = RegisterForm()

    context = {'form': form}
    return render(request, 'registration/register.html', context)
