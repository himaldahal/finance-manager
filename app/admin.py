from django.contrib import admin
from .models import Balance, Transaction, TransactionType
from django.forms import HiddenInput
from django.contrib.auth import get_user_model
from django import forms

User = get_user_model()


class TransactionAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'date', 'transaction_type',  'transaction_of','category')
    class Meta:
        model = Transaction
        fields = '__all__'
        widgets = {
            'transaction_of': HiddenInput(),
        }

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["category"].queryset = TransactionType.objects.filter(added_by=request.user)
        form.base_fields['transaction_of'].queryset = User.objects.filter(pk=request.user.pk)
        form.base_fields['transaction_of'].initial = request.user.pk

        return form

    def get_queryset(self, request): 
        qs = super().get_queryset(request) 
        return qs.filter(category__added_by=request.user)
 

class TransactionTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(added_by=request.user)


class BalanceAdmin(admin.ModelAdmin):
    list_display = ('balance',)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(balance_of=request.user)

admin.site.register(Transaction, TransactionAdmin)
admin.site.register(TransactionType, TransactionTypeAdmin)
admin.site.register(Balance, BalanceAdmin)


# panel customization
admin.site.site_header = 'Finance Manager Administration'
admin.site.site_title = 'Finance Manager Admin'
admin.site.index_title = 'Finance Manager Dashboard'
