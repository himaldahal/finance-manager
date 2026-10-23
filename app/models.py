import datetime
from decimal import Decimal

import django
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from .icons import ACCOUNT_ICONS, ICON_CHOICES

MAX_AMOUNT = Decimal("999999999.99")
MIN_AMOUNT = Decimal("0.01")
MIN_DATE = datetime.date(2000, 1, 1)

KIND_CHOICES = (("expense", "Expense"), ("income", "Income"))
CATEGORY_KIND_CHOICES = (("both", "Income and expense"), ("expense", "Expense only"), ("income", "Income only"))

# A small calm palette; the CSS defines one class per key.
COLOR_CHOICES = (
    ("gray", "Gray"),
    ("blue", "Blue"),
    ("teal", "Teal"),
    ("green", "Green"),
    ("olive", "Olive"),
    ("amber", "Amber"),
    ("red", "Red"),
    ("plum", "Plum"),
)

NUMBER_FORMATS = (
    ("intl", "1,234,567.89"),
    ("indian", "12,34,567.89"),
    ("eu", "1.234.567,89"),
    ("space", "1 234 567,89"),
)


def check_constraint(condition, name):
    """CheckConstraint spelled for both Django 4.2 (check=) and 5.1+ (condition=)."""
    if django.VERSION >= (5, 1):
        return models.CheckConstraint(condition=condition, name=name)
    return models.CheckConstraint(check=condition, name=name)


def validate_date(value):
    latest = timezone.localdate() + datetime.timedelta(days=1)
    if value < MIN_DATE:
        raise ValidationError(f"Date cannot be before {MIN_DATE.isoformat()}.")
    if value > latest:
        raise ValidationError("Date cannot be in the future.")


amount_validators = [MinValueValidator(MIN_AMOUNT), MaxValueValidator(MAX_AMOUNT)]


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    currency_code = models.CharField(max_length=3, default="NPR")
    currency_symbol = models.CharField(max_length=5, default="Rs")
    number_format = models.CharField(max_length=10, choices=NUMBER_FORMATS, default="intl")
    # None means "use the ALLOW_NEGATIVE_BALANCE setting".
    allow_negative_balance = models.BooleanField(null=True, blank=True, default=None)
    onboarding_dismissed = models.BooleanField(default=False)
    setup_done = models.BooleanField(default=False)
    # Optional second currency shown next to the main one, with a manually entered rate:
    # 1 unit of the main currency = secondary_rate units of the secondary currency.
    secondary_currency_code = models.CharField(max_length=3, blank=True, default="")
    secondary_rate = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return f"Profile of {self.user}"


class Category(models.Model):
    name = models.CharField(max_length=50)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categories")
    kind = models.CharField(max_length=7, choices=CATEGORY_KIND_CHOICES, default="both")
    color = models.CharField(max_length=10, choices=COLOR_CHOICES, default="gray")
    icon = models.CharField(max_length=30, choices=ICON_CHOICES, default="tag")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")

    class Meta:
        ordering = [Lower("name")]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint(Lower("name"), "user", name="uniq_category_name_per_user"),
        ]

    def __str__(self):
        return self.name

    def accepts(self, kind):
        return self.kind in ("both", kind)

    @property
    def full_name(self):
        return f"{self.parent.name} / {self.name}" if self.parent_id else self.name


ACCOUNT_TYPES = (("bank", "Bank"), ("cash", "Cash"), ("wallet", "Wallet"), ("credit", "Credit"))


class Account(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts")
    name = models.CharField(max_length=60)
    type = models.CharField(max_length=10, choices=ACCOUNT_TYPES, default="bank")
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ("archived", Lower("name"))
        constraints = [models.UniqueConstraint(Lower("name"), "user", name="uniq_account_name_per_user")]

    def __str__(self):
        return self.name

    @property
    def icon(self):
        return ACCOUNT_ICONS.get(self.type, "wallet")

    @property
    def is_credit(self):
        return self.type == "credit"


class Tag(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=30)

    class Meta:
        ordering = [Lower("name")]
        constraints = [models.UniqueConstraint(Lower("name"), "user", name="uniq_tag_name_per_user")]

    def __str__(self):
        return self.name


class ActiveTransactionManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Transaction(models.Model):
    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=amount_validators)
    date = models.DateField(default=timezone.localdate, validators=[validate_date])
    kind = models.CharField(max_length=7, default="expense", choices=KIND_CHOICES)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    category = models.ForeignKey(Category, on_delete=models.RESTRICT, related_name="transactions")
    note = models.TextField(blank=True, default="", max_length=1000)
    payee = models.CharField(max_length=80, blank=True, default="")
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.RESTRICT, related_name="transactions")
    tags = models.ManyToManyField(Tag, blank=True, related_name="transactions")
    recurring = models.ForeignKey(
        "RecurringTransaction", null=True, blank=True, on_delete=models.SET_NULL, related_name="transactions"
    )
    recurring_date = models.DateField(null=True, blank=True)
    split_group = models.UUIDField(null=True, blank=True, db_index=True)
    reconciled = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ActiveTransactionManager()
    all_objects = models.Manager()

    class Meta:
        ordering = ("-date", "-id")
        indexes = [models.Index(fields=["user", "date"], name="tx_user_date")]
        constraints = [
            check_constraint(Q(amount__gt=0), "tx_amount_positive"),
            models.UniqueConstraint(
                fields=["recurring", "recurring_date"],
                condition=Q(recurring__isnull=False),
                name="uniq_recurring_occurrence",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def effect(self):
        """Signed effect on the balance."""
        return self.amount if self.kind == "income" else -self.amount

    def clean(self):
        super().clean()
        if self.category_id and self.user_id:
            if self.category.user_id != self.user_id:
                raise ValidationError({"category": "Choose one of your own categories."})
            if not self.category.accepts(self.kind):
                raise ValidationError({"category": f"This category cannot be used for {self.kind} transactions."})
        if self.account_id and self.user_id and self.account.user_id != self.user_id:
            raise ValidationError({"account": "Choose one of your own accounts."})


class Budget(models.Model):
    """A spending limit for one month. ``category`` empty means the overall monthly budget."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budgets")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.CASCADE, related_name="budgets")
    month = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=amount_validators)
    rollover = models.BooleanField(default=False)
    warn_percent = models.PositiveSmallIntegerField(default=80, validators=[MinValueValidator(1), MaxValueValidator(99)])

    class Meta:
        ordering = ("month", "id")
        constraints = [
            models.UniqueConstraint(fields=["user", "category", "month"], name="uniq_budget_per_category_month"),
            models.UniqueConstraint(fields=["user", "month"], condition=Q(category__isnull=True), name="uniq_overall_budget_month"),
            check_constraint(Q(amount__gt=0), "budget_amount_positive"),
        ]

    def __str__(self):
        return f"{self.category or 'Overall'} budget {self.month:%Y-%m}"


class CategoryRule(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rules")
    pattern = models.CharField(max_length=60)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="rules")
    priority = models.PositiveSmallIntegerField(default=100)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("priority", "id")

    def __str__(self):
        return f"{self.pattern} -> {self.category}"


class Transfer(models.Model):
    """Money moved between two of the user's accounts. Not income and not an expense."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transfers")
    from_account = models.ForeignKey(Account, on_delete=models.RESTRICT, related_name="transfers_out")
    to_account = models.ForeignKey(Account, on_delete=models.RESTRICT, related_name="transfers_in")
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=amount_validators)
    date = models.DateField(default=timezone.localdate, validators=[validate_date])
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ("-date", "-id")
        constraints = [
            check_constraint(Q(amount__gt=0), "transfer_amount_positive"),
            check_constraint(~Q(from_account=models.F("to_account")), "transfer_distinct_accounts"),
        ]

    def __str__(self):
        return f"{self.from_account} -> {self.to_account}"


class Goal(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="goals")
    name = models.CharField(max_length=80)
    target_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=amount_validators)
    target_date = models.DateField(null=True, blank=True)
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.SET_NULL, related_name="goals")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="goals")
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self):
        return self.name


class Contribution(models.Model):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="contributions")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.localdate, validators=[validate_date])
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ("-date", "-id")


class SavedView(models.Model):
    """A named set of transaction filters (a query string)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views")
    name = models.CharField(max_length=60)
    query = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = [Lower("name")]
        constraints = [models.UniqueConstraint(Lower("name"), "user", name="uniq_view_name_per_user")]


class RecurringTransaction(models.Model):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    FREQUENCY_CHOICES = ((MONTHLY, "Monthly"), (WEEKLY, "Weekly"))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recurring")
    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=amount_validators)
    kind = models.CharField(max_length=7, default="expense", choices=KIND_CHOICES)
    category = models.ForeignKey(Category, on_delete=models.RESTRICT, related_name="recurring")
    note = models.TextField(blank=True, default="", max_length=1000)
    payee = models.CharField(max_length=80, blank=True, default="")
    account = models.ForeignKey(Account, null=True, blank=True, on_delete=models.RESTRICT, related_name="recurring")
    frequency = models.CharField(max_length=7, choices=FREQUENCY_CHOICES, default=MONTHLY)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    next_due = models.DateField()
    active = models.BooleanField(default=True)
    last_error = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering = ("name", "id")

    def __str__(self):
        return self.name


class AuditEntry(models.Model):
    """One change to a transaction. Keeps working after the transaction itself is purged."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="audit_entries")
    transaction_id = models.BigIntegerField(db_index=True)
    action = models.CharField(max_length=12)  # created, updated, deleted, restored, recategorised, imported
    summary = models.CharField(max_length=300, blank=True, default="")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")


class MonthLock(models.Model):
    """A closed month: transactions dated in it cannot be added, changed or removed until unlocked."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="month_locks")
    month = models.DateField()

    class Meta:
        ordering = ("-month",)
        constraints = [models.UniqueConstraint(fields=["user", "month"], name="uniq_month_lock")]


class Person(models.Model):
    """Someone you lend to, borrow from, or share bills with. No account needed."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="people")
    name = models.CharField(max_length=60)

    class Meta:
        ordering = [Lower("name")]
        verbose_name_plural = "people"
        constraints = [models.UniqueConstraint(Lower("name"), "user", name="uniq_person_name_per_user")]

    def __str__(self):
        return self.name


LEDGER_KINDS = (
    ("lent", "I lent money"),
    ("borrowed", "I borrowed money"),
    ("split_me", "I paid a shared bill"),
    ("split_them", "They paid a shared bill"),
    ("paid_me", "They paid me back"),
    ("paid_them", "I paid them back"),
)


class LedgerEntry(models.Model):
    """A signed amount: positive means the person owes you more, negative means you owe them more."""

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="entries")
    kind = models.CharField(max_length=10, choices=LEDGER_KINDS)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=120, blank=True, default="")
    date = models.DateField(default=timezone.localdate, validators=[validate_date])
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-date", "-id")
