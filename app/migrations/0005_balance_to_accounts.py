from decimal import Decimal

from django.db import migrations
from django.db.models import Q, Sum


def net_of(Transaction, user_id):
    totals = Transaction.objects.filter(user_id=user_id).aggregate(
        income=Sum("amount", filter=Q(kind="income")),
        expense=Sum("amount", filter=Q(kind="expense")),
    )
    return (totals["income"] or Decimal("0")) - (totals["expense"] or Decimal("0"))


def balances_to_accounts(apps, schema_editor):
    """Replace the mutable Balance table with a derived balance.

    Every user gets a "Main account" holding all of their existing transactions.
    Its opening balance is the old stored balance minus the net of the user's
    transactions, so each user's displayed balance is exactly what it was.
    """
    User = apps.get_model("auth", "User")
    Balance = apps.get_model("app", "Balance")
    Account = apps.get_model("app", "Account")
    Profile = apps.get_model("app", "Profile")
    Transaction = apps.get_model("app", "Transaction")

    for user in User.objects.all().iterator():
        net = net_of(Transaction, user.id)
        row = Balance.objects.filter(balance_of_id=user.id).order_by("-id").first()
        opening = (row.balance - net) if row is not None else Decimal("0")
        account = Account.objects.create(
            user_id=user.id, name="Main account", type="bank", opening_balance=opening.quantize(Decimal("0.01")))
        Transaction.objects.filter(user_id=user.id).update(account_id=account.id)
        Profile.objects.get_or_create(user_id=user.id)


def accounts_to_balances(apps, schema_editor):
    Balance = apps.get_model("app", "Balance")
    Account = apps.get_model("app", "Account")
    Transaction = apps.get_model("app", "Transaction")
    for user_id in Account.objects.values_list("user_id", flat=True).distinct():
        opening = sum((a.opening_balance for a in Account.objects.filter(user_id=user_id)), Decimal("0"))
        Balance.objects.create(balance_of_id=user_id, balance=opening + net_of(Transaction, user_id))


class Migration(migrations.Migration):
    dependencies = [("app", "0004_extend_schema")]

    operations = [
        migrations.RunPython(balances_to_accounts, accounts_to_balances),
        migrations.DeleteModel(name="Balance"),
    ]
