from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User
import datetime

class TransactionType(models.Model):
    name = models.CharField(max_length=50)
    added_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ('expense', 'Expense'),
        ('income', 'Income'),
    )
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.now)
    transaction_type = models.CharField(max_length=7,default="expense", choices=TRANSACTION_TYPES)
    transaction_of = models.ForeignKey(User, on_delete=models.CASCADE,default=None)
    category = models.ForeignKey(TransactionType, on_delete=models.CASCADE)
    remarks = models.TextField(blank=True,null=True)


    def save(self, *args, **kwargs):
        if not self.pk:
            # New transaction, update balance of user
            balance = Balance.objects.filter(balance_of=self.transaction_of).first()
            if balance is None:
                balance = Balance(balance=0, balance_of=self.transaction_of)
            if self.transaction_type == 'expense':
                if self.amount > balance.balance:
                    return  # Ignore the request
                balance.balance -= self.amount
            elif self.transaction_type == 'income':
                balance.balance += self.amount
            balance.save()

        super().save(*args, **kwargs)
        
    class Meta:
        ordering = ('-date',)

    def __str__(self):
        return self.name


class Balance(models.Model):
    balance = models.DecimalField(max_digits=10, decimal_places=2)
    balance_of = models.ForeignKey(User, on_delete=models.CASCADE)
    
    def __str__(self):
        return f"{self.balance}"