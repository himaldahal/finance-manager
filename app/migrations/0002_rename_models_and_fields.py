from django.db import migrations


class Migration(migrations.Migration):
    """Rename the original models and fields to clearer names (no data change)."""

    dependencies = [("app", "0001_initial")]

    operations = [
        migrations.RenameModel(old_name="TransactionType", new_name="Category"),
        migrations.RenameField(model_name="category", old_name="added_by", new_name="user"),
        migrations.RenameField(model_name="transaction", old_name="transaction_of", new_name="user"),
        migrations.RenameField(model_name="transaction", old_name="transaction_type", new_name="kind"),
        migrations.RenameField(model_name="transaction", old_name="remarks", new_name="note"),
    ]
