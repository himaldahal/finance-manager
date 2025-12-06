from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import Account, Category, Transaction
from .services import TransactionService

class TransactionServiceTestCase(TestCase):
    def setUp(self):
        """Set up a test user and a transaction category."""
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.account = Account.objects.create(name='Test Account', owner=self.user, opening_balance=Decimal('1000.00'), balance=Decimal('1000.00'))
        self.category = Category.objects.create(name='Test Category', user=self.user)

    def test_create_income_transaction(self):
        """Test creating an income transaction updates balance."""
        payload = {
            'name': 'Salary',
            'amount': Decimal('500.00'),
            'transaction_type': 'income',
            'user': self.user,
            'account': self.account,
            'category': self.category
        }
        TransactionService.create_transaction(payload)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1500.00'))

    def test_create_expense_transaction(self):
        """Test creating an expense transaction updates balance."""
        payload = {
            'name': 'Groceries',
            'amount': Decimal('50.00'),
            'transaction_type': 'expense',
            'user': self.user,
            'account': self.account,
            'category': self.category
        }
        TransactionService.create_transaction(payload)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('950.00'))

    def test_create_expense_transaction_insufficient_balance(self):
        """Test creating an expense transaction with insufficient balance."""
        payload = {
            'name': 'Luxury Car',
            'amount': Decimal('2000.00'),
            'transaction_type': 'expense',
            'user': self.user,
            'account': self.account,
            'category': self.category
        }
        with self.assertRaises(ValidationError):
            TransactionService.create_transaction(payload)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))


    def test_create_transfer_transaction(self):
        """Test creating a transfer transaction updates balances."""
        to_account = Account.objects.create(name='Savings', owner=self.user, opening_balance=Decimal('500.00'), balance=Decimal('500.00'))
        payload = {
            'name': 'Transfer to savings',
            'amount': Decimal('200.00'),
            'transaction_type': 'transfer',
            'user': self.user,
            'account': self.account,
            'to_account': to_account,
            'category': self.category
        }
        TransactionService.create_transaction(payload)
        self.account.refresh_from_db()
        to_account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('800.00'))
        self.assertEqual(to_account.balance, Decimal('700.00'))

    def test_update_income_transaction_amount(self):
        """Test updating an income transaction's amount."""
        transaction = TransactionService.create_transaction({
            'name': 'Consulting Gig',
            'amount': Decimal('300.00'),
            'transaction_type': 'income',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        TransactionService.update_transaction(transaction, {'amount': Decimal('400.00')})

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1400.00'))

    def test_update_expense_transaction_amount(self):
        """Test updating an expense transaction's amount."""
        transaction = TransactionService.create_transaction({
            'name': 'Dinner',
            'amount': Decimal('50.00'),
            'transaction_type': 'expense',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        TransactionService.update_transaction(transaction, {'amount': Decimal('75.00')})

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('925.00'))

    def test_update_transaction_to_insufficient_balance(self):
        """Test that updating an expense to an amount greater than the balance fails."""
        transaction = TransactionService.create_transaction({
            'name': 'Small Purchase',
            'amount': Decimal('100.00'),
            'transaction_type': 'expense',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        with self.assertRaises(ValidationError):
            TransactionService.update_transaction(transaction, {'amount': Decimal('1200.00')})

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_update_transaction_type(self):
        """Test updating a transaction's type from income to expense."""
        transaction = TransactionService.create_transaction({
            'name': 'Refund',
            'amount': Decimal('100.00'),
            'transaction_type': 'income',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        TransactionService.update_transaction(transaction, {'transaction_type': 'expense'})

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('900.00'))

    def test_update_transaction_account(self):
        """Test updating a transaction's account."""
        new_account = Account.objects.create(name='New Account', owner=self.user, opening_balance=Decimal('0.00'), balance=Decimal('0.00'))
        transaction = TransactionService.create_transaction({
            'name': 'Initial Deposit',
            'amount': Decimal('200.00'),
            'transaction_type': 'income',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        TransactionService.update_transaction(transaction, {'account': new_account})

        self.account.refresh_from_db()
        new_account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        self.assertEqual(new_account.balance, Decimal('200.00'))

    def test_delete_income_transaction(self):
        """Test deleting an income transaction correctly reverts balance."""
        transaction = TransactionService.create_transaction({
            'name': 'Services Rendered',
            'amount': Decimal('150.00'),
            'transaction_type': 'income',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        TransactionService.delete_transaction(transaction)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        transaction.refresh_from_db()
        self.assertTrue(transaction.is_deleted)

    def test_delete_expense_transaction(self):
        """Test deleting an expense transaction correctly reverts balance."""
        transaction = TransactionService.create_transaction({
            'name': 'Office Supplies',
            'amount': Decimal('30.00'),
            'transaction_type': 'expense',
            'user': self.user,
            'account': self.account,
            'category': self.category
        })

        TransactionService.delete_transaction(transaction)

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))
        transaction.refresh_from_db()
        self.assertTrue(transaction.is_deleted)
