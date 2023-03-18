from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
import datetime

class TransactionType(models.Model):
    name = models.CharField(max_length=50)

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
    category = models.ForeignKey(TransactionType, on_delete=models.CASCADE)
    remarks = models.TextField(blank=True,null=True)

    def save(self, *args, **kwargs):
     if  Balance.objects.filter().all().count() < 1:
        balance_obj = Balance()
        balance_obj.balance = 0
        balance_obj.save()
        
     if self.transaction_type == 'expense':
        balance = Balance.objects.first()
        if self.amount > balance.balance:
            return  # Ignore the request
        balance.balance -= self.amount
        balance.save()
     elif self.transaction_type == 'income':
        balance = Balance.objects.first()
        balance.balance += self.amount
        balance.save()
     super().save(*args, **kwargs)
    
    class Meta:
        ordering =('-date',)

    def __str__(self):
        return self.name


class Balance(models.Model):
    balance = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.balance}"