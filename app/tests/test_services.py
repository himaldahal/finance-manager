import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import override_settings

from app import services
from app.models import Account, AuditEntry, Budget, CategoryRule, MonthLock, Tag, Transaction, Transfer

from .base import AppTestCase, today


class BalanceTests(AppTestCase):
    def test_balance_is_opening_plus_income_minus_expense(self):
        account = self.account()
        account.opening_balance = Decimal("100.00")
        account.save()
        self.tx(amount="50", kind="income")
        self.tx(amount="30.25", kind="expense")
        self.assertEqual(services.balance_for(self.user), Decimal("119.75"))

    def test_balance_scoped_to_user(self):
        self.tx(amount="50", kind="income")
        self.tx(user=self.other, amount="999", kind="income")
        self.assertEqual(services.balance_for(self.user), Decimal("50.00"))

    def test_deleted_transactions_do_not_count(self):
        t = self.tx(amount="50", kind="income")
        services.delete_transactions(self.user, Transaction.objects.filter(pk=t.pk))
        self.assertEqual(services.balance_for(self.user), Decimal("0.00"))

    def test_balance_before_date(self):
        self.tx(amount="10", kind="income", date=today() - datetime.timedelta(days=5))
        self.tx(amount="7", kind="income", date=today())
        self.assertEqual(services.balance_for(self.user, before=today()), Decimal("10.00"))

    def test_account_balances_include_transfers(self):
        a = self.account()
        b = Account.objects.create(user=self.user, name="Cash", type="cash")
        self.tx(amount="100", kind="income")
        services.create_transfer(Transfer(user=self.user, from_account=a, to_account=b, amount=Decimal("40"), date=today()))
        balances = services.account_balances(self.user)
        self.assertEqual(balances[a.pk], Decimal("60.00"))
        self.assertEqual(balances[b.pk], Decimal("40.00"))
        self.assertEqual(services.balance_for(self.user), Decimal("100.00"))

    def test_decimal_precision_never_float(self):
        for _ in range(10):
            self.tx(amount="0.10", kind="income")
        self.assertEqual(services.balance_for(self.user), Decimal("1.00"))


class OverdraftTests(AppTestCase):
    def test_allowed_by_default(self):
        t = self.tx(amount="500", kind="expense")
        services.save_transaction(t)
        self.assertLess(services.balance_for(self.user), 0)

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_blocked_with_clear_error_and_nothing_saved(self):
        t = Transaction(user=self.user, name="Big", amount=Decimal("500"), date=today(), kind="expense",
                        category=self.cat(), account=self.account())
        with self.assertRaises(ValidationError) as ctx:
            services.save_transaction(t)
        self.assertIn("below zero", str(ctx.exception))
        self.assertFalse(Transaction.objects.filter(name="Big").exists())

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_user_preference_overrides_setting(self):
        profile = services.get_profile(self.user)
        profile.allow_negative_balance = True
        profile.save()
        services.forget_profile(self.user)
        t = Transaction(user=self.user, name="Big", amount=Decimal("500"), date=today(), kind="expense",
                        category=self.cat(), account=self.account())
        services.save_transaction(t)
        self.assertTrue(Transaction.objects.filter(name="Big").exists())

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_editing_amount_up_is_checked(self):
        self.tx(amount="100", kind="income")
        t = self.tx(amount="50", kind="expense")
        t.amount = Decimal("150")
        with self.assertRaises(ValidationError):
            services.save_transaction(t)

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_deleting_income_cannot_overdraw(self):
        income = self.tx(amount="100", kind="income")
        self.tx(amount="80", kind="expense")
        with self.assertRaises(ValidationError):
            services.delete_transactions(self.user, Transaction.objects.filter(pk=income.pk))

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_credit_accounts_may_go_negative(self):
        card = Account.objects.create(user=self.user, name="Card", type="credit")
        t = Transaction(user=self.user, name="Buy", amount=Decimal("90"), date=today(), kind="expense",
                        category=self.cat(), account=card)
        services.save_transaction(t)
        self.assertEqual(services.account_balances(self.user)[card.pk], Decimal("-90.00"))

    @override_settings(ALLOW_NEGATIVE_BALANCE=False)
    def test_transfer_checks_source_account(self):
        a = self.account()
        b = Account.objects.create(user=self.user, name="Cash", type="cash")
        with self.assertRaises(ValidationError):
            services.create_transfer(Transfer(user=self.user, from_account=a, to_account=b, amount=Decimal("5"), date=today()))

    def test_message_formats_in_users_currency(self):
        with override_settings(ALLOW_NEGATIVE_BALANCE=False):
            try:
                services.ensure_funds(self.user, Decimal("-5"))
            except ValidationError as exc:
                self.assertIn("Rs 0.00", str(exc))


class MutationTests(AppTestCase):
    def test_save_assigns_default_account_and_logs(self):
        t = Transaction(user=self.user, name="Tea", amount=Decimal("3"), date=today(), kind="expense", category=self.cat())
        saved = services.save_transaction(t)
        self.assertIsNotNone(saved.account_id)
        self.assertTrue(AuditEntry.objects.filter(transaction_id=saved.pk, action="created").exists())

    def test_update_logs_changed_fields(self):
        t = self.tx(amount="5")
        t.amount = Decimal("9")
        services.save_transaction(t)
        entry = AuditEntry.objects.filter(transaction_id=t.pk, action="updated").first()
        self.assertIn("amount", entry.summary)

    def test_tags_are_created_case_insensitively(self):
        t = Transaction(user=self.user, name="Tea", amount=Decimal("3"), date=today(), kind="expense",
                        category=self.cat(), account=self.account())
        saved = services.save_transaction(t, tags=["Work", "work", "  Home  "])
        self.assertEqual(sorted(x.name for x in saved.tags.all()), ["Home", "Work"])
        self.assertEqual(Tag.objects.filter(user=self.user).count(), 2)

    def test_restore_round_trip(self):
        t = self.tx()
        services.delete_transactions(self.user, Transaction.objects.filter(pk=t.pk))
        self.assertEqual(services.restore_transactions(self.user, [t.pk]), [t.pk])
        self.assertTrue(Transaction.objects.filter(pk=t.pk).exists())

    def test_purge_respects_30_day_window(self):
        old = self.tx()
        new = self.tx()
        Transaction.all_objects.filter(pk=old.pk).update(deleted_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31))
        Transaction.all_objects.filter(pk=new.pk).update(deleted_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5))
        self.assertEqual(services.purge_deleted(), 1)
        self.assertTrue(Transaction.all_objects.filter(pk=new.pk).exists())

    def test_split_creates_linked_transactions(self):
        base = Transaction(user=self.user, name="Market", date=today(), kind="expense", account=self.account())
        made = services.create_split(self.user, base, [(self.cat(name="Groceries"), Decimal("30")), (self.cat(name="Health"), Decimal("20"))])
        self.assertEqual(len(made), 2)
        self.assertEqual(len({t.split_group for t in made}), 1)
        self.assertEqual(services.balance_for(self.user), Decimal("-50.00"))


class LockTests(AppTestCase):
    def test_closed_month_blocks_changes(self):
        t = self.tx()
        MonthLock.objects.create(user=self.user, month=today().replace(day=1))
        t.name = "changed"
        with self.assertRaises(ValidationError):
            services.save_transaction(t)
        with self.assertRaises(ValidationError):
            services.delete_transactions(self.user, Transaction.objects.filter(pk=t.pk))
        new = Transaction(user=self.user, name="n", amount=Decimal("1"), date=today(), kind="expense",
                          category=self.cat(), account=self.account())
        with self.assertRaises(ValidationError):
            services.save_transaction(new)

    def test_moving_a_transaction_out_of_a_closed_month_is_blocked(self):
        t = self.tx(date=today())
        MonthLock.objects.create(user=self.user, month=today().replace(day=1))
        t.date = today() - datetime.timedelta(days=40)
        with self.assertRaises(ValidationError):
            services.save_transaction(t)

    def test_other_months_unaffected(self):
        MonthLock.objects.create(user=self.user, month=services.add_months(today().replace(day=1), -3))
        t = Transaction(user=self.user, name="n", amount=Decimal("1"), date=today(), kind="expense",
                        category=self.cat(), account=self.account())
        services.save_transaction(t)

    def test_transfers_respect_locks(self):
        MonthLock.objects.create(user=self.user, month=today().replace(day=1))
        b = Account.objects.create(user=self.user, name="Cash", type="cash")
        with self.assertRaises(ValidationError):
            services.create_transfer(Transfer(user=self.user, from_account=self.account(), to_account=b, amount=Decimal("1"), date=today()))


class RuleTests(AppTestCase):
    def test_first_matching_rule_by_priority(self):
        CategoryRule.objects.create(user=self.user, pattern="cafe", category=self.cat(name="Dining out"), priority=50)
        CategoryRule.objects.create(user=self.user, pattern="cafe", category=self.cat(name="Other"), priority=10)
        self.assertEqual(services.suggest_category(self.user, "Cafe Mitini").name, "Other")

    def test_kind_and_active_and_scope(self):
        CategoryRule.objects.create(user=self.user, pattern="pay", category=self.cat(name="Salary"))
        self.assertIsNone(services.suggest_category(self.user, "payday", "expense"))
        self.assertEqual(services.suggest_category(self.user, "payday", "income").name, "Salary")
        CategoryRule.objects.create(user=self.other, pattern="zzz", category=self.cat(self.other, "Rent"))
        self.assertIsNone(services.suggest_category(self.user, "zzz"))
        CategoryRule.objects.filter(user=self.user).update(active=False)
        self.assertIsNone(services.suggest_category(self.user, "payday"))
        self.assertIsNone(services.suggest_category(self.user, ""))


class MonthHelperTests(AppTestCase):
    def test_add_months_clamps(self):
        self.assertEqual(services.add_months(datetime.date(2025, 1, 31), 1), datetime.date(2025, 2, 28))
        self.assertEqual(services.add_months(datetime.date(2025, 1, 31), 13), datetime.date(2026, 2, 28))
        self.assertEqual(services.add_months(datetime.date(2025, 3, 15), -3), datetime.date(2024, 12, 15))

    def test_parse_month(self):
        self.assertEqual(services.parse_month("2025-03"), datetime.date(2025, 3, 1))
        default = services.month_start(today())
        self.assertEqual(services.parse_month("garbage"), default)
        self.assertEqual(services.parse_month("1990-01"), default)
        self.assertEqual(services.parse_month(None), default)

    def test_default_categories_idempotent(self):
        before = self.user.categories.count()
        services.create_default_categories(self.user)
        self.assertEqual(self.user.categories.count(), before)
