from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import Account, Category, Transaction

User = get_user_model()


class TransactionAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "date", "transaction_type", "account", "category")
    list_filter = ("transaction_type", "date", "category")
    search_fields = ("name", "remarks")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["account"].queryset = Account.objects.filter(
            owner=request.user
        )
        form.base_fields["category"].queryset = Category.objects.filter(
            user=request.user
        )
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(user=request.user)


class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "user")
    list_filter = ("user",)
    search_fields = ("name",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(user=request.user)


class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "account_type", "balance", "owner")
    list_filter = ("account_type",)
    search_fields = ("name",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(owner=request.user)


admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Account, AccountAdmin)


# panel customization
admin.site.site_header = "Finance Manager Administration"
admin.site.site_title = "Finance Manager Admin"
admin.site.index_title = "Finance Manager Dashboard"
