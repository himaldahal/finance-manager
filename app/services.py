from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import Account, Transaction

class TransactionService:
    @staticmethod
    def create_transaction(payload: dict) -> Transaction:
        """
        Creates a new transaction and updates account balances atomically.
        """
        with transaction.atomic():
            account = payload['account']
            amount = payload['amount']
            transaction_type = payload['transaction_type']

            if transaction_type in ['expense', 'transfer']:
                if account.balance < amount:
                    raise ValidationError("Insufficient balance to complete this transaction.")

            transaction_instance = Transaction.objects.create(**payload)

            if transaction_type == 'income':
                account.balance += amount
            elif transaction_type == 'expense':
                account.balance -= amount
            elif transaction_type == 'transfer':
                account.balance -= amount
                to_account = payload['to_account']
                to_account.balance += amount
                to_account.save()

            account.save()
            return transaction_instance

    @staticmethod
    def update_transaction(transaction_instance: Transaction, payload: dict) -> Transaction:
        """
        Updates a transaction and adjusts account balances atomically.
        """
        with transaction.atomic():
            old_transaction = Transaction.objects.select_for_update().get(pk=transaction_instance.pk)

            # Revert the old transaction's effect
            if old_transaction.transaction_type == 'income':
                old_transaction.account.balance -= old_transaction.amount
            elif old_transaction.transaction_type == 'expense':
                old_transaction.account.balance += old_transaction.amount
            elif old_transaction.transaction_type == 'transfer':
                old_transaction.account.balance += old_transaction.amount
                if old_transaction.to_account:
                    old_transaction.to_account.balance -= old_transaction.amount
                    old_transaction.to_account.save()
            old_transaction.account.save()

            # Apply the new transaction's effect
            account = payload.get('account', old_transaction.account)
            amount = payload.get('amount', old_transaction.amount)
            transaction_type = payload.get('transaction_type', old_transaction.transaction_type)

            if transaction_type in ['expense', 'transfer']:
                # Temporarily apply the change to check for insufficient balance
                if account.balance < amount:
                     raise ValidationError("Insufficient balance to complete this transaction.")

            if transaction_type == 'income':
                account.balance += amount
            elif transaction_type == 'expense':
                account.balance -= amount
            elif transaction_type == 'transfer':
                account.balance -= amount
                to_account = payload.get('to_account', old_transaction.to_.account)
                if to_account:
                    to_account.balance += amount
                    to_account.save()
            account.save()

            # Update the transaction instance
            for key, value in payload.items():
                setattr(transaction_instance, key, value)
            transaction_instance.save()

            return transaction_instance

    @staticmethod
    def delete_transaction(transaction_instance: Transaction):
        """
        Soft-deletes a transaction and reverts its effect on account balances.
        """
        with transaction.atomic():
            if not transaction_instance.is_deleted:
                if transaction_instance.transaction_type == 'income':
                    transaction_instance.account.balance -= transaction_instance.amount
                elif transaction_instance.transaction_type == 'expense':
                    transaction_instance.account.balance += transaction_instance.amount
                elif transaction_instance.transaction_type == 'transfer':
                    transaction_instance.account.balance += transaction_instance.amount
                    if transaction_instance.to_account:
                        transaction_instance.to_account.balance -= transaction_instance.amount
                        transaction_instance.to_account.save()

                transaction_instance.account.save()
                transaction_instance.is_deleted = True
                transaction_instance.save()
