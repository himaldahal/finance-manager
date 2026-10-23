"""Migrate a database created with the ORIGINAL schema (0001) forward and check that data survives."""
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OldSchemaMigrationTests(TransactionTestCase):
    start = [("app", "0001_initial")]

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.start)
        self.old = self.executor.loader.project_state(self.start).apps
        User = self.old.get_model("auth", "User")
        Cat = self.old.get_model("app", "TransactionType")
        Tx = self.old.get_model("app", "Transaction")
        Bal = self.old.get_model("app", "Balance")

        self.u1 = User.objects.create(username="old1", password="x")
        self.u2 = User.objects.create(username="old2", password="x")
        self.u3 = User.objects.create(username="old3", password="x")
        food = Cat.objects.create(name="Food", added_by=self.u1)
        dup = Cat.objects.create(name="food ", added_by=self.u1)
        pay = Cat.objects.create(name="  Pay  ", added_by=self.u1)
        other = Cat.objects.create(name="Food", added_by=self.u2)
        mk = lambda user, cat, name, amount, kind, remarks=None: Tx.objects.create(  # noqa: E731
            name=name, amount=Decimal(amount), transaction_type=kind, transaction_of=user, category=cat, remarks=remarks, date="2025-01-10")
        mk(self.u1, pay, "  Padded name  ", "100.00", "income")
        mk(self.u1, food, "Lunch", "30.00", "expense", "tasty")
        mk(self.u1, dup, "Dinner", "5.00", "expense")
        mk(self.u1, food, "Negative", "-5.00", "expense")
        mk(self.u1, food, "Zero", "0.00", "expense")
        mk(self.u1, food, "x" * 200, "1.00", "expense")
        mk(self.u2, other, "Other user", "10.00", "expense")
        Bal.objects.create(balance_of=self.u1, balance=Decimal("150.50"))
        Bal.objects.create(balance_of=self.u2, balance=Decimal("-10.00"))
        # u3 has no Balance row and no data

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def migrate_forward(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        return executor.loader.project_state(executor.loader.graph.leaf_nodes()).apps

    def test_data_is_preserved_and_balance_is_identical(self):
        apps = self.migrate_forward()
        Tx = apps.get_model("app", "Transaction")
        Cat = apps.get_model("app", "Category")
        Account = apps.get_model("app", "Account")
        Profile = apps.get_model("app", "Profile")
        User = apps.get_model("auth", "User")

        def balance(user):
            from django.db.models import Sum
            acct = Account.objects.get(user=user)
            inc = Tx.objects.filter(user=user, kind="income").aggregate(t=Sum("amount"))["t"] or 0
            exp = Tx.objects.filter(user=user, kind="expense").aggregate(t=Sum("amount"))["t"] or 0
            return acct.opening_balance + inc - exp

        u1, u2, u3 = (User.objects.get(username=n) for n in ("old1", "old2", "old3"))
        self.assertEqual(balance(u1), Decimal("150.50"))   # what the old Balance row said
        self.assertEqual(balance(u2), Decimal("-10.00"))
        self.assertEqual(balance(u3), Decimal("0.00"))
        self.assertEqual(Account.objects.get(user=u1).name, "Main account")
        self.assertEqual(Account.objects.filter(user=u3).count(), 1)

    def test_clean_up_rules(self):
        apps = self.migrate_forward()
        Tx = apps.get_model("app", "Transaction")
        Cat = apps.get_model("app", "Category")
        User = apps.get_model("auth", "User")
        u1 = User.objects.get(username="old1")
        names = sorted(Cat.objects.filter(user=u1).values_list("name", flat=True))
        self.assertEqual(names, ["Food", "Pay"])                      # duplicates merged, names trimmed
        self.assertEqual(Cat.objects.filter(user__username="old2", name="Food").count(), 1)
        self.assertEqual(Tx.objects.get(name="Dinner").category.name, "Food")
        negative = Tx.objects.get(name="Negative")
        self.assertEqual((negative.amount, negative.kind), (Decimal("5.00"), "income"))
        self.assertFalse(Tx.objects.filter(name="Zero").exists())      # zero amounts removed
        self.assertTrue(Tx.objects.filter(name="Padded name").exists())
        self.assertEqual(Tx.objects.get(name="Lunch").note, "tasty")
        self.assertEqual(Tx.objects.get(name="Padded name").note, "")
        self.assertTrue(Tx.objects.filter(name="x" * 120).exists())    # long names truncated
        self.assertEqual(Tx.objects.filter(user=u1).count(), 5)
        self.assertEqual(Tx.objects.filter(user__username="old2").count(), 1)

    def test_existing_users_skip_first_run_setup_and_get_profiles(self):
        apps = self.migrate_forward()
        Profile = apps.get_model("app", "Profile")
        self.assertEqual(Profile.objects.count(), 3)
        self.assertFalse(Profile.objects.filter(setup_done=False).exists())

    def test_transactions_attached_to_account_and_not_deleted(self):
        apps = self.migrate_forward()
        Tx = apps.get_model("app", "Transaction")
        self.assertFalse(Tx.objects.filter(account__isnull=True).exists())
        self.assertFalse(Tx.objects.filter(deleted_at__isnull=False).exists())

    def test_balance_table_is_gone(self):
        self.migrate_forward()
        self.assertNotIn("app_balance", connection.introspection.table_names())
