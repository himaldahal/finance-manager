from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import Transaction, TransactionType, Balance

class ModelTestCase(TestCase):
    def setUp(self):
        """Set up a test user and a transaction category."""
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.category = TransactionType.objects.create(name='Test Category', added_by=self.user)

    def test_balance_object_creation_on_first_transaction(self):
        """Test that a Balance object is created if none exists when a transaction is made."""
        self.assertFalse(Balance.objects.filter(balance_of=self.user).exists())
        Transaction.objects.create(
            name='Initial Income',
            amount=Decimal('100.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        self.assertTrue(Balance.objects.filter(balance_of=self.user).exists())
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('100.00'))

    def test_transaction_creation_income(self):
        """Test creating an income transaction updates balance."""
        Transaction.objects.create(
            name='Salary',
            amount=Decimal('500.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('500.00'))

        Transaction.objects.create(
            name='Bonus',
            amount=Decimal('200.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('700.00'))

    def test_transaction_creation_expense(self):
        """Test creating an expense transaction updates balance."""
        # Initial income
        Transaction.objects.create(
            name='Initial Deposit',
            amount=Decimal('1000.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('1000.00'))

        # Expense
        Transaction.objects.create(
            name='Groceries',
            amount=Decimal('50.00'),
            transaction_type='expense',
            transaction_of=self.user,
            category=self.category
        )
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('950.00'))

    def test_transaction_update_amount(self):
        """Test updating transaction amount correctly updates balance."""
        transaction = Transaction.objects.create(
            name='Freelance Gig',
            amount=Decimal('300.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('300.00'))

        transaction.amount = Decimal('350.00')
        transaction.save()
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('350.00'))

        # Update expense
        expense_transaction = Transaction.objects.create(
            name='Dinner',
            amount=Decimal('40.00'),
            transaction_type='expense',
            transaction_of=self.user,
            category=self.category
        )
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('310.00')) # 350 - 40

        expense_transaction.amount = Decimal('60.00')
        expense_transaction.save()
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('290.00')) # 350 - 60

    def test_transaction_update_type(self):
        """Test updating transaction type (income to expense and vice-versa)."""
        transaction = Transaction.objects.create(
            name='Consulting Fee',
            amount=Decimal('200.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('200.00'))

        # Change income to expense
        transaction.transaction_type = 'expense'
        transaction.save()
        balance.refresh_from_db()
        # Expected: -200 (original income reverted) - 200 (new expense) = -400 from original state.
        # Since original state was 0, then +200, now it should be 0 - 200 (reverted) - 200 (new expense) = -400.
        # However, the balance object started at 0, became 200.
        # Reverting income: 200 - 200 = 0. Applying new expense: 0 - 200 = -200.
        self.assertEqual(balance.balance, Decimal('-200.00'))


        # Change expense back to income
        # Current balance is -200. Transaction amount is 200, type is expense.
        transaction.transaction_type = 'income'
        transaction.save()
        balance.refresh_from_db()
        # Reverting expense: -200 + 200 = 0. Applying new income: 0 + 200 = 200.
        self.assertEqual(balance.balance, Decimal('200.00'))

    def test_transaction_deletion(self):
        """Test deleting a transaction correctly reverts balance."""
        # Initial income to have some balance
        Transaction.objects.create(
            name='Initial Funding',
            amount=Decimal('100.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        
        transaction_to_delete = Transaction.objects.create(
            name='Services Rendered',
            amount=Decimal('150.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('250.00')) # 100 + 150

        transaction_to_delete.delete()
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('100.00'))

        # Test deleting an expense
        expense_to_delete = Transaction.objects.create(
            name='Office Supplies',
            amount=Decimal('30.00'),
            transaction_type='expense',
            transaction_of=self.user,
            category=self.category
        )
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('70.00')) # 100 - 30

        expense_to_delete.delete()
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('100.00'))


    def test_insufficient_balance_model_level(self):
        """Test ValidationError for expense exceeding balance at model level."""
        Transaction.objects.create(
            name='Small Income',
            amount=Decimal('20.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('20.00'))

        with self.assertRaisesMessage(ValidationError, "Insufficient balance to complete this transaction."):
            expense_transaction = Transaction(
                name='Large Expense',
                amount=Decimal('100.00'),
                transaction_type='expense',
                transaction_of=self.user,
                category=self.category
            )
            # The custom save method raises ValidationError directly
            expense_transaction.save() 
            # If save didn't raise, full_clean() would, but our save does.
            # expense_transaction.full_clean() 

        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('20.00')) # Balance should remain unchanged

    def test_transaction_update_to_insufficient_balance(self):
        """Test updating an expense to exceed balance."""
        Transaction.objects.create(
            name='Initial Income',
            amount=Decimal('50.00'),
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        expense = Transaction.objects.create(
            name='Small Expense',
            amount=Decimal('10.00'),
            transaction_type='expense',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('40.00')) # 50 - 10

        expense.amount = Decimal('60.00') # Original was 10, new is 60. Balance is 40. 40 + 10 (revert) = 50. 50 < 60.
        with self.assertRaisesMessage(ValidationError, "Insufficient balance to complete this transaction."):
            expense.save()
        
        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('40.00')) # Balance should be unchanged by failed update.
        
        # Verify the transaction in DB is also unchanged
        expense_from_db = Transaction.objects.get(pk=expense.pk)
        self.assertEqual(expense_from_db.amount, Decimal('10.00'))

    def test_transaction_type_change_to_insufficient_balance(self):
        """Test changing transaction type from income to expense leading to insufficient balance."""
        # User has 0 balance initially
        income_tx = Transaction.objects.create(
            name='Payment',
            amount=Decimal('30.00'), # User gets 30
            transaction_type='income',
            transaction_of=self.user,
            category=self.category
        )
        balance = Balance.objects.get(balance_of=self.user)
        self.assertEqual(balance.balance, Decimal('30.00'))

        # Try to change this income of 30 to an expense of 30.
        # Balance is 30. Revert income: 30 - 30 = 0. New expense: 0 - 30 = -30. This should be allowed.
        # Let's try changing to a larger expense.
        # income_tx.amount = Decimal('100.00') # This would fail if we were testing amount update
        
        # Change type to expense. Current amount is 30.
        # Balance is 30. Revert income of 30: balance becomes 0.
        # Apply expense of 30: balance becomes -30. This is fine if no insufficient balance check was there for negative.
        # Our check is `self.amount > balance.balance`.
        # If balance is 0, and self.amount is 30, then 30 > 0, ValidationError.
        
        income_tx.transaction_type = 'expense'
        # Before save: old type=income, old amount=30. New type=expense, new amount=30.
        # Balance = 30.
        # Revert original: balance += original_amount (if expense) or balance -= original_amount (if income)
        # Here, original was income, so balance becomes 30 - 30 = 0.
        # Apply current: balance -= self.amount (if expense) or balance += self.amount (if income)
        # Here, current is expense, so balance becomes 0 - 30 = -30.
        # The check `if self.amount > balance.balance` becomes `if 30 > 0`, which is true.
        # So this should raise ValidationError.

        with self.assertRaisesMessage(ValidationError, "Insufficient balance to complete this transaction."):
            income_tx.save()

        balance.refresh_from_db()
        self.assertEqual(balance.balance, Decimal('30.00')) # Should remain unchanged
        income_tx_from_db = Transaction.objects.get(pk=income_tx.pk)
        self.assertEqual(income_tx_from_db.transaction_type, 'income') # Type should not have changed
        self.assertEqual(income_tx_from_db.amount, Decimal('30.00'))

    # Test for concurrent transactions is complex and often requires more than unit tests.
    # We'll skip a direct test for select_for_update here as per instructions.
    # The presence of select_for_update in models.py is the key change.
    # Manual testing or integration tests are better suited for true concurrency.

    def tearDown(self):
        self.user.delete()
        self.category.delete()
        # Balance objects should be deleted via CASCADE when User is deleted.
        # Transaction objects should be deleted via CASCADE when User or TransactionType is deleted.

# More tests can be added for edge cases, like zero amount transactions if allowed/disallowed.
# Or tests for TransactionType model if it had more logic.
# For now, this covers the balance logic in Transaction model.
