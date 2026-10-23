from django.contrib import admin

from . import models as m


@admin.register(m.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "kind", "color", "parent")
    list_filter = ("kind",)
    search_fields = ("name", "user__username")


@admin.register(m.Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("name", "amount", "kind", "date", "category", "user", "deleted_at")
    list_filter = ("kind", "date")
    search_fields = ("name", "payee", "user__username")
    raw_id_fields = ("user", "category", "recurring", "account")

    def get_queryset(self, request):
        return m.Transaction.all_objects.all()


for model, columns in (
    (m.Account, ("name", "type", "opening_balance", "user", "archived")),
    (m.Tag, ("name", "user")),
    (m.Budget, ("category", "month", "amount", "user")),
    (m.CategoryRule, ("pattern", "category", "priority", "active", "user")),
    (m.Transfer, ("from_account", "to_account", "amount", "date", "user")),
    (m.Goal, ("name", "target_amount", "target_date", "user")),
    (m.Contribution, ("goal", "amount", "date")),
    (m.RecurringTransaction, ("name", "amount", "kind", "frequency", "next_due", "active", "user")),
    (m.Profile, ("user", "currency_code", "number_format")),
    (m.SavedView, ("name", "user")),
):
    admin.site.register(model, type(f"{model.__name__}Admin", (admin.ModelAdmin,), {"list_display": columns}))

admin.site.site_header = "Finance Manager administration"
admin.site.site_title = "Finance Manager admin"
admin.site.index_title = "Administration"
