import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from app.models import Account, Budget, Category, Profile, Tag, Transaction, Transfer
from app.formatting import format_money, format_number

from .base import AppTestCase, today


class TransactionModelTests(AppTestCase):
    def test_effect_sign(self):
        self.assertEqual(self.tx(kind="income").effect, Decimal("10.00"))
        self.assertEqual(self.tx(kind="expense").effect, Decimal("-10.00"))

    def test_default_manager_hides_deleted(self):
        t = self.tx()
        Transaction.all_objects.filter(pk=t.pk).update(deleted_at=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc))
        self.assertFalse(Transaction.objects.filter(pk=t.pk).exists())
        self.assertTrue(Transaction.all_objects.filter(pk=t.pk).exists())

    def test_amount_must_be_positive_in_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.tx(amount="0")

    def test_validators_reject_out_of_range(self):
        t = Transaction(user=self.user, name="x", amount=Decimal("0.00"), date=today(), kind="expense",
                        category=self.cat(), account=self.account())
        with self.assertRaises(ValidationError):
            t.full_clean()
        t.amount = Decimal("1000000000.00")
        with self.assertRaises(ValidationError):
            t.full_clean()

    def test_date_validation(self):
        t = Transaction(user=self.user, name="x", amount=Decimal("5"), date=datetime.date(1990, 1, 1), kind="expense",
                        category=self.cat(), account=self.account())
        with self.assertRaises(ValidationError):
            t.full_clean()
        t.date = today() + datetime.timedelta(days=30)
        with self.assertRaises(ValidationError):
            t.full_clean()

    def test_clean_rejects_foreign_category_and_account(self):
        t = Transaction(user=self.user, name="x", amount=Decimal("5"), date=today(), kind="expense",
                        category=self.cat(self.other), account=self.account())
        with self.assertRaises(ValidationError):
            t.full_clean()
        t = Transaction(user=self.user, name="x", amount=Decimal("5"), date=today(), kind="expense",
                        category=self.cat(), account=self.account(self.other))
        with self.assertRaises(ValidationError):
            t.full_clean()

    def test_category_kind_compatibility(self):
        salary = self.cat(name="Salary")
        t = Transaction(user=self.user, name="x", amount=Decimal("5"), date=today(), kind="expense", category=salary,
                        account=self.account())
        with self.assertRaises(ValidationError):
            t.full_clean()


class CategoryModelTests(AppTestCase):
    def test_name_unique_per_user_case_insensitive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Category.objects.create(user=self.user, name="GROCERIES")

    def test_same_name_allowed_for_other_user(self):
        self.assertTrue(Category.objects.filter(user=self.other, name="Groceries").exists())

    def test_accepts_and_full_name(self):
        parent = self.cat()
        child = Category.objects.create(user=self.user, name="Snacks", parent=parent, kind="expense")
        self.assertEqual(child.full_name, "Groceries / Snacks")
        self.assertTrue(child.accepts("expense"))
        self.assertFalse(child.accepts("income"))
        self.assertTrue(self.cat(name="Other").accepts("income"))


class MiscModelTests(AppTestCase):
    def test_profile_created_by_signal(self):
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_budget_constraints(self):
        month = today().replace(day=1)
        Budget.objects.create(user=self.user, category=None, month=month, amount=Decimal("100"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Budget.objects.create(user=self.user, category=None, month=month, amount=Decimal("200"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Budget.objects.create(user=self.user, category=self.cat(), month=month, amount=Decimal("-5"))

    def test_transfer_requires_distinct_accounts(self):
        a = self.account()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transfer.objects.create(user=self.user, from_account=a, to_account=a, amount=Decimal("5"))

    def test_tag_unique_case_insensitive(self):
        Tag.objects.create(user=self.user, name="Work")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Tag.objects.create(user=self.user, name="work")

    def test_account_properties(self):
        self.assertEqual(Account(type="credit").icon, "credit-card")
        self.assertTrue(Account(type="credit").is_credit)

    def test_str_methods(self):
        t = self.tx(name="Tea")
        self.assertEqual(str(t), "Tea")
        self.assertEqual(str(self.cat()), "Groceries")
        self.assertIn("alice", str(self.user.profile))


class FormattingTests(TestCase):
    def test_number_formats(self):
        self.assertEqual(format_number("1234567.891", "intl"), "1,234,567.89")
        self.assertEqual(format_number("1234567.891", "indian"), "12,34,567.89")
        self.assertEqual(format_number("1234567.891", "eu"), "1.234.567,89")
        self.assertEqual(format_number("1234567.891", "space"), "1 234 567,89")
        self.assertEqual(format_number("-5", "intl"), "-5.00")
        self.assertEqual(format_number("12", "intl", places=0), "12")

    def test_money_symbol_spacing(self):
        class P:
            currency_symbol = "Rs"
            number_format = "intl"

        class D(P):
            currency_symbol = "$"

        self.assertEqual(format_money("1500", P()), "Rs 1,500.00")
        self.assertEqual(format_money("-1500", D()), "-$1,500.00")
        self.assertEqual(format_money("1500", None), "1,500.00")
        self.assertEqual(format_money("3", P(), with_symbol=False), "3.00")
