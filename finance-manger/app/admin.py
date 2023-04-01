from django.contrib import admin
from .models import Balance, Transaction, TransactionType
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('name', 'amount', 'date', 'transaction_type', 'category', 'remarks')
    # pass

class TransactionTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)


class BalanceAdmin(admin.ModelAdmin):
    list_display = ('balance',)

admin.site.register(Transaction, TransactionAdmin)
admin.site.register(TransactionType, TransactionTypeAdmin)
admin.site.register(Balance, BalanceAdmin)
