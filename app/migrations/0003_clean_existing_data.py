from decimal import Decimal

from django.db import migrations


def clean(apps, schema_editor):
    """Bring rows created under the old, unvalidated schema in line with the new rules.

    * missing notes become empty strings
    * names are trimmed and truncated to the new limits
    * categories whose names collide case-insensitively per user are merged
    * negative amounts are flipped to positive with the opposite kind
      (an expense of -5 is an income of 5); zero amounts are removed
    """
    Category = apps.get_model("app", "Category")
    Transaction = apps.get_model("app", "Transaction")

    seen = {}
    for cat in Category.objects.order_by("id"):
        name = (cat.name or "").strip()[:50] or "Uncategorised"
        key = (cat.user_id, name.lower())
        keeper = seen.get(key)
        if keeper is None:
            seen[key] = cat
            if cat.name != name:
                cat.name = name
                cat.save(update_fields=["name"])
        else:
            Transaction.objects.filter(category_id=cat.id).update(category_id=keeper.id)
            cat.delete()

    for tx in Transaction.objects.all().iterator():
        changed = False
        if tx.note is None:
            tx.note = ""
            changed = True
        name = (tx.name or "").strip()[:120] or "Untitled"
        if name != tx.name:
            tx.name = name
            changed = True
        if tx.amount is not None and tx.amount <= 0:
            if tx.amount == 0:
                tx.delete()
                continue
            tx.amount = abs(tx.amount)
            tx.kind = "income" if tx.kind == "expense" else "expense"
            changed = True
        if tx.amount is not None and tx.amount > Decimal("999999999.99"):
            tx.amount = Decimal("999999999.99")
            changed = True
        if changed:
            tx.save()


class Migration(migrations.Migration):
    dependencies = [("app", "0002_rename_models_and_fields")]

    operations = [migrations.RunPython(clean, migrations.RunPython.noop)]
