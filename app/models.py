from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Account(models.Model):
    ACCOUNT_TYPES = (
        ("wallet", "Wallet"),
        ("bank", "Bank"),
        ("mobile_money", "Mobile Money"),
    )
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    opening_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # Storing icon and color information is a good idea for the frontend
    icon = models.CharField(max_length=50, blank=True, null=True)
    color = models.CharField(max_length=7, blank=True, null=True)  # e.g., '#FF5733'

    def __str__(self):
        return self.name


class Transaction(models.Model):
    TRANSACTION_TYPES = (
        ("expense", "Expense"),
        ("income", "Income"),
        ("transfer", "Transfer"),
    )

    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="transactions"
    )
    # For transfers, this will be the destination account
    to_account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="transfers_to",
    )

    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=8, choices=TRANSACTION_TYPES)

    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True
    )

    date = models.DateField(default=timezone.now)
    remarks = models.TextField(blank=True, null=True)

    # Attachment support
    attachment = models.FileField(upload_to="attachments/", blank=True, null=True)

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft deletion
    is_deleted = models.BooleanField(default=False)

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.name} - {self.get_transaction_type_display()} - {self.amount}"

    class Meta:
        ordering = ("-date",)
