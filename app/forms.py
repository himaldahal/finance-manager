import datetime
import unicodedata
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.db import transaction
from django.utils import timezone

from . import services
from .models import (
    MAX_AMOUNT,
    MIN_AMOUNT,
    MIN_DATE,
    NUMBER_FORMATS,
    Account,
    Budget,
    Category,
    CategoryRule,
    Contribution,
    Goal,
    KIND_CHOICES,
    LEDGER_KINDS,
    LedgerEntry,
    Person,
    RecurringTransaction,
    SavedView,
    Transaction,
    Transfer,
    validate_date,
)

User = get_user_model()

CATEGORY_ERROR = {"invalid_choice": "Choose one of your own categories."}
ACCOUNT_ERROR = {"invalid_choice": "Choose one of your own accounts."}
MAX_TAGS = 10


def password_min_length():
    """The configured minimum password length (exposed to the browser so both sides agree)."""
    for validator in settings.AUTH_PASSWORD_VALIDATORS:
        if validator["NAME"].endswith("MinimumLengthValidator"):
            return validator.get("OPTIONS", {}).get("min_length", 8)
    return 8


def password_widget_attrs(field, **extra):
    """Mark a password field for the browser-side checks and drop the static rules list."""
    field.help_text = ""
    field.widget.attrs.update({"data-min-length": str(password_min_length()), **extra})


def split_name(full_name):
    parts = (full_name or "").split(None, 1)
    first = parts[0][:150] if parts else ""
    last = parts[1].strip()[:150] if len(parts) > 1 else ""
    return first, last


class TagsField(forms.Field):
    """Accepts a list (JSON) or a comma separated string; returns a list of clean names."""

    def to_python(self, value):
        if value in (None, ""):
            return []
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple)):
            raise forms.ValidationError("Tags must be a list of names.")
        names = []
        for raw in value:
            name = " ".join(str(raw).split())
            if not name:
                continue
            if len(name) > 30:
                raise forms.ValidationError("A tag can have at most 30 characters.")
            if name.lower() not in [n.lower() for n in names]:
                names.append(name)
        if len(names) > MAX_TAGS:
            raise forms.ValidationError(f"Use at most {MAX_TAGS} tags.")
        return names


class TransactionForm(forms.ModelForm):
    tags = TagsField(required=False)

    class Meta:
        model = Transaction
        fields = ["name", "amount", "date", "kind", "category", "account", "payee", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }
        error_messages = {"category": CATEGORY_ERROR, "account": ACCOUNT_ERROR}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        self.fields["category"].queryset = Category.objects.filter(user=user)
        self.fields["category"].required = False
        accounts = Account.objects.filter(user=user, archived=False)
        if self.instance.account_id:
            accounts = Account.objects.filter(user=user, pk__in=[a.pk for a in accounts] + [self.instance.account_id])
        self.fields["account"].queryset = accounts
        self.fields["account"].required = False

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        category = cleaned.get("category")
        if not category and kind and "category" not in self.errors:
            text = f"{cleaned.get('name', '')} {cleaned.get('payee', '')}"
            category = services.suggest_category(self.user, text, kind)
            if category is None:
                self.add_error("category", "Choose a category.")
            else:
                cleaned["category"] = category
                self.instance.category = category
        if category and kind and not category.accepts(kind):
            self.add_error("category", f"This category cannot be used for {kind} transactions.")
        return cleaned

    @property
    def tag_names(self):
        return self.cleaned_data.get("tags", [])


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "kind", "color", "icon", "parent"]
        error_messages = {"parent": {"invalid_choice": "Choose one of your own categories."}}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        parents = Category.objects.filter(user=user, parent__isnull=True)
        if self.instance.pk:
            parents = parents.exclude(pk=self.instance.pk)
        self.fields["parent"].queryset = parents
        self.fields["parent"].required = False

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Category.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"You already have a category named “{name}”.")
        return name

    def clean_kind(self):
        kind = self.cleaned_data["kind"]
        if self.instance.pk and kind != "both":
            other = "income" if kind == "expense" else "expense"
            if Transaction.all_objects.filter(category=self.instance, kind=other).exists():
                raise forms.ValidationError(f"This category already has {other} transactions.")
        return kind

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if parent and self.instance.pk and Category.objects.filter(parent=self.instance).exists():
            raise forms.ValidationError("A category that has sub-categories cannot become a sub-category.")
        return parent


def _signed_amount(**kwargs):
    return forms.DecimalField(max_digits=14, decimal_places=2, min_value=-MAX_AMOUNT, max_value=MAX_AMOUNT, **kwargs)


class AccountForm(forms.ModelForm):
    opening_balance = _signed_amount(required=False, initial=0)

    class Meta:
        model = Account
        fields = ["name", "type", "opening_balance", "archived"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Account.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"You already have an account named “{name}”.")
        return name

    def clean_opening_balance(self):
        value = self.cleaned_data.get("opening_balance")
        return services.ZERO if value is None else value


class TransferForm(forms.ModelForm):
    class Meta:
        model = Transfer
        fields = ["from_account", "to_account", "amount", "date", "note"]
        error_messages = {"from_account": ACCOUNT_ERROR, "to_account": ACCOUNT_ERROR}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        accounts = Account.objects.filter(user=user, archived=False)
        self.fields["from_account"].queryset = accounts
        self.fields["to_account"].queryset = accounts

    def clean(self):
        cleaned = super().clean()
        a, b = cleaned.get("from_account"), cleaned.get("to_account")
        if a and b and a.pk == b.pk:
            self.add_error("to_account", "Choose two different accounts.")
        return cleaned


class SplitForm(forms.Form):
    """One purchase over several categories."""

    name = forms.CharField(max_length=120)
    date = forms.DateField(validators=[validate_date])
    kind = forms.ChoiceField(choices=KIND_CHOICES)
    account = forms.ModelChoiceField(queryset=Account.objects.none(), required=False, error_messages=ACCOUNT_ERROR)
    payee = forms.CharField(max_length=80, required=False)
    note = forms.CharField(max_length=1000, required=False)
    tags = TagsField(required=False)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, required=False)
    splits = forms.Field()

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["account"].queryset = Account.objects.filter(user=user, archived=False)
        self._parts = []

    def clean_splits(self):
        value = self.cleaned_data["splits"]
        if not isinstance(value, list) or not 2 <= len(value) <= 12:
            raise forms.ValidationError("Split the purchase into 2 to 12 parts.")
        return value

    def clean(self):
        cleaned = super().clean()
        raw = cleaned.get("splits")
        kind = cleaned.get("kind")
        if not raw or not kind:
            return cleaned
        from decimal import Decimal, InvalidOperation

        parts, total = [], Decimal("0.00")
        cats = {c.pk: c for c in Category.objects.filter(user=self.user)}
        for i, row in enumerate(raw, start=1):
            try:
                category = cats[int(row.get("category"))]
                amount = Decimal(str(row.get("amount")))
                if not amount.is_finite() or amount < MIN_AMOUNT or amount > MAX_AMOUNT or amount != amount.quantize(Decimal("0.01")):
                    raise InvalidOperation
            except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
                self.add_error("splits", f"Part {i}: choose one of your categories and a positive amount with at most 2 decimals.")
                return cleaned
            if not category.accepts(kind):
                self.add_error("splits", f"Part {i}: {category.name} cannot be used for {kind} transactions.")
                return cleaned
            parts.append((category, amount))
            total += amount
        if cleaned.get("amount") is not None and cleaned["amount"] != total:
            self.add_error("amount", f"The parts add up to {total}, not {cleaned['amount']}.")
        self._parts = parts
        return cleaned

    def parts(self):
        return self._parts

    def base_transaction(self):
        d = self.cleaned_data
        return Transaction(user=self.user, name=d["name"].strip(), date=d["date"], kind=d["kind"], account=d.get("account"),
                           payee=d.get("payee", ""), note=d.get("note", ""), amount=sum((a for _, a in self._parts), services.ZERO))


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["name"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        clash = Person.objects.filter(user=self.user, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError(f"You already track someone called \u201c{name}\u201d.")
        return name


class LedgerEntryForm(forms.Form):
    kind = forms.ChoiceField(choices=LEDGER_KINDS)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=MIN_AMOUNT, max_value=MAX_AMOUNT, required=False)
    total = forms.DecimalField(max_digits=12, decimal_places=2, min_value=MIN_AMOUNT, max_value=MAX_AMOUNT, required=False)
    my_share = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0, max_value=MAX_AMOUNT, required=False)
    description = forms.CharField(max_length=120, required=False)
    date = forms.DateField(validators=[validate_date], required=False)
    due_date = forms.DateField(required=False)

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        if kind in ("split_me", "split_them") and cleaned.get("total") is not None:
            total = cleaned["total"]
            mine = cleaned.get("my_share")
            if mine is None:
                mine = (total / 2).quantize(Decimal("0.01"))
            if mine >= total:
                self.add_error("my_share", "Your share must be less than the total.")
                return cleaned
            cleaned["amount"] = (total - mine) if kind == "split_me" else mine
            if cleaned["amount"] <= 0:
                self.add_error("my_share", "Your share must be more than zero for a bill they paid.")
        if cleaned.get("amount") is None and not self.errors:
            self.add_error("amount", "Enter an amount.")
        due = cleaned.get("due_date")
        if due and due < MIN_DATE:
            self.add_error("due_date", "Date is too far in the past.")
        return cleaned

    def build(self, person):
        d = self.cleaned_data
        sign = 1 if d["kind"] in ("lent", "split_me", "paid_them") else -1
        return LedgerEntry(person=person, kind=d["kind"], amount=sign * d["amount"], description=d.get("description", ""),
                           date=d.get("date") or timezone.localdate(), due_date=d.get("due_date"))


class RuleForm(forms.ModelForm):
    class Meta:
        model = CategoryRule
        fields = ["pattern", "category", "priority", "active"]
        error_messages = {"category": CATEGORY_ERROR}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        self.fields["category"].queryset = Category.objects.filter(user=user)
        self.fields["priority"].required = False
        self.fields["active"].required = False

    def clean_pattern(self):
        pattern = " ".join(self.cleaned_data["pattern"].split())
        if len(pattern) < 2:
            raise forms.ValidationError("Use at least 2 characters.")
        return pattern

    def clean_priority(self):
        value = self.cleaned_data.get("priority")
        return 100 if value is None else value


class BudgetForm(forms.Form):
    category = forms.ModelChoiceField(queryset=Category.objects.none(), required=False, error_messages=CATEGORY_ERROR)
    month = forms.CharField()
    amount = forms.DecimalField(min_value=MIN_AMOUNT, max_value=MAX_AMOUNT, max_digits=12, decimal_places=2)
    rollover = forms.BooleanField(required=False)
    warn_percent = forms.IntegerField(min_value=1, max_value=99, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["category"].queryset = Category.objects.filter(user=user, kind__in=("both", "expense"))

    def clean_month(self):
        value = self.cleaned_data["month"]
        month = services.parse_month(value, default=None) if len(str(value)) == 7 else None
        if month is None or str(value) != month.strftime("%Y-%m"):
            raise forms.ValidationError("Use a month like 2025-03.")
        return month

    def save(self):
        data = self.cleaned_data
        defaults = {"amount": data["amount"], "rollover": data["rollover"]}
        if data.get("warn_percent"):
            defaults["warn_percent"] = data["warn_percent"]
        budget, _ = Budget.objects.update_or_create(
            user=self.user, category=data.get("category"), month=data["month"], defaults=defaults)
        return budget


class GoalForm(forms.ModelForm):
    class Meta:
        model = Goal
        fields = ["name", "target_amount", "target_date", "account", "category"]
        error_messages = {"category": CATEGORY_ERROR, "account": ACCOUNT_ERROR}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        self.fields["account"].queryset = Account.objects.filter(user=user)
        self.fields["category"].queryset = Category.objects.filter(user=user)

    def clean_target_date(self):
        value = self.cleaned_data.get("target_date")
        if value and value < MIN_DATE:
            raise forms.ValidationError("Date is too far in the past.")
        if value and value > timezone.localdate() + datetime.timedelta(days=365 * 50):
            raise forms.ValidationError("Date is too far in the future.")
        return value


class ContributionForm(forms.ModelForm):
    amount = _signed_amount()

    class Meta:
        model = Contribution
        fields = ["amount", "date", "note"]

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if value == 0:
            raise forms.ValidationError("Enter an amount other than zero.")
        return value


class SavedViewForm(forms.ModelForm):
    class Meta:
        model = SavedView
        fields = ["name", "query"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        self.fields["query"].required = False

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if SavedView.objects.filter(user=self.user, name__iexact=name).exists():
            raise forms.ValidationError("You already have a view with that name.")
        return name

    def clean_query(self):
        return (self.cleaned_data.get("query") or "").lstrip("?")


class RecurringForm(forms.ModelForm):
    class Meta:
        model = RecurringTransaction
        fields = ["name", "amount", "kind", "category", "account", "payee", "note", "frequency", "start_date", "end_date"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}), "end_date": forms.DateInput(attrs={"type": "date"})}
        error_messages = {"category": CATEGORY_ERROR, "account": ACCOUNT_ERROR}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.instance.user = user
        self.fields["category"].queryset = Category.objects.filter(user=user)
        self.fields["account"].queryset = Account.objects.filter(user=user, archived=False)
        self.fields["account"].required = False
        self._schedule_before = (self.instance.start_date, self.instance.frequency) if self.instance.pk else None

    def clean_start_date(self):
        value = self.cleaned_data["start_date"]
        if value < MIN_DATE:
            raise forms.ValidationError(f"Date cannot be before {MIN_DATE.isoformat()}.")
        if value > timezone.localdate() + datetime.timedelta(days=366):
            raise forms.ValidationError("Start date is too far in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "End date must be on or after the start date.")
        category, kind = cleaned.get("category"), cleaned.get("kind")
        if category and kind and not category.accepts(kind):
            self.add_error("category", f"This category cannot be used for {kind} transactions.")
        return cleaned

    def save(self, commit=True):
        item = super().save(commit=False)
        if self._schedule_before is None:
            item.next_due = item.start_date
        elif self._schedule_before != (item.start_date, item.frequency):
            last = (
                Transaction.all_objects.filter(recurring=item).order_by("-recurring_date")
                .values_list("recurring_date", flat=True).first()
            )
            floor = item.start_date if last is None else max(item.start_date, last + datetime.timedelta(days=1))
            item.next_due = services.first_due_on_or_after(item, floor)
        if item.end_date and item.next_due > item.end_date:
            item.active = False
        if commit:
            item.save()
        return item


class RegisterForm(UserCreationForm):
    full_name = forms.CharField(max_length=100, label="Full name")
    email = forms.EmailField(max_length=254)

    class Meta:
        model = User
        fields = ("full_name", "username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        password_widget_attrs(self.fields["password1"], **{
            "data-strength": "1", "data-similar-to": "id_full_name id_username id_email"})
        password_widget_attrs(self.fields["password2"], **{"data-match": "id_password1"})
        self.fields["username"].help_text = ""
        self.fields["username"].widget.attrs["maxlength"] = "150"

    def clean_username(self):
        username = unicodedata.normalize("NFKC", self.cleaned_data["username"]).strip().lower()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name, user.last_name = split_name(self.cleaned_data["full_name"])
        if commit:
            with transaction.atomic():
                user.save()
                services.set_up_new_user(user)
        return user


NEGATIVE_CHOICES = (("", "Use the site default"), ("yes", "Allow"), ("no", "Block with an error"))


class SettingsForm(forms.Form):
    display_name = forms.CharField(max_length=100, label="Display name")
    currency_code = forms.CharField(min_length=3, max_length=3, label="Currency code")
    currency_symbol = forms.CharField(max_length=5, label="Currency symbol")
    number_format = forms.ChoiceField(choices=NUMBER_FORMATS, label="Number format")
    allow_negative_balance = forms.ChoiceField(choices=NEGATIVE_CHOICES, required=False, label="Overdrafts")
    secondary_currency_code = forms.CharField(max_length=3, required=False, label="Also show amounts in")
    secondary_rate = forms.DecimalField(max_digits=16, decimal_places=6, min_value=Decimal("0.000001"), required=False,
                                        label="Exchange rate")

    def __init__(self, *args, user, **kwargs):
        self.user = user
        profile = services.get_profile(user)
        pref = {None: "", True: "yes", False: "no"}[profile.allow_negative_balance]
        kwargs.setdefault("initial", {
            "display_name": f"{user.first_name} {user.last_name}".strip(),
            "currency_code": profile.currency_code,
            "currency_symbol": profile.currency_symbol,
            "number_format": profile.number_format,
            "allow_negative_balance": pref,
            "secondary_currency_code": profile.secondary_currency_code,
            "secondary_rate": profile.secondary_rate,
        })
        super().__init__(*args, **kwargs)

    def clean_secondary_currency_code(self):
        code = self.cleaned_data.get("secondary_currency_code", "").strip().upper()
        if code and not (code.isascii() and code.isalpha() and len(code) == 3):
            raise forms.ValidationError("Use a three letter code such as USD.")
        return code

    def clean(self):
        cleaned = super().clean()
        code, rate = cleaned.get("secondary_currency_code"), cleaned.get("secondary_rate")
        if code and not rate:
            self.add_error("secondary_rate", "Enter how many units of that currency one unit of your main currency is worth.")
        if rate and not code:
            self.add_error("secondary_currency_code", "Enter the currency code for this rate.")
        return cleaned

    def clean_currency_code(self):
        code = self.cleaned_data["currency_code"].strip().upper()
        if not (code.isascii() and code.isalpha()):
            raise forms.ValidationError("Use a three letter code such as NPR or USD.")
        return code

    def clean_currency_symbol(self):
        symbol = self.cleaned_data["currency_symbol"].strip()
        if not symbol or any(unicodedata.category(c).startswith("C") or c.isspace() for c in symbol):
            raise forms.ValidationError("Enter 1 to 5 visible characters.")
        return symbol

    def save(self):
        data = self.cleaned_data
        profile = services.get_profile(self.user)
        profile.currency_code = data["currency_code"]
        profile.currency_symbol = data["currency_symbol"]
        profile.number_format = data["number_format"]
        profile.allow_negative_balance = {"": None, "yes": True, "no": False}[data["allow_negative_balance"] or ""]
        profile.secondary_currency_code = data.get("secondary_currency_code", "")
        profile.secondary_rate = data.get("secondary_rate") if profile.secondary_currency_code else None
        profile.save()
        self.user.first_name, self.user.last_name = split_name(data["display_name"])
        self.user.save(update_fields=["first_name", "last_name"])
        services.forget_profile(self.user)


class ChangePasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = kwargs.get("user") or (args[0] if args else None)
        words = " ".join(filter(None, [getattr(user, "username", ""), getattr(user, "email", ""),
                                       getattr(user, "first_name", ""), getattr(user, "last_name", "")]))
        password_widget_attrs(self.fields["new_password1"], **{"data-strength": "1", "data-similar-words": words})
        password_widget_attrs(self.fields["new_password2"], **{"data-match": "id_new_password1"})


class ImportForm(forms.Form):
    file = forms.FileField(label="CSV file")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > settings.FILE_UPLOAD_MAX_MEMORY_SIZE // 2:
            raise forms.ValidationError("The file is too large (limit 512 KB).")
        if not upload.name.lower().endswith(".csv"):
            raise forms.ValidationError("Upload a .csv file.")
        return upload


class SetupForm(forms.Form):
    """First-run setup: currency, accounts, starter categories, optional budget and sample data."""

    currency_code = forms.CharField(min_length=3, max_length=3, label="Currency code")
    currency_symbol = forms.CharField(max_length=5, label="Currency symbol")
    number_format = forms.ChoiceField(choices=NUMBER_FORMATS, label="Number format")
    main_name = forms.CharField(max_length=60, label="Main account name")
    main_opening = _signed_amount(required=False, label="Current balance")
    cash = forms.BooleanField(required=False, label="I also keep cash")
    cash_opening = _signed_amount(required=False, label="Cash on hand")
    wallet = forms.BooleanField(required=False, label="I use a mobile wallet")
    wallet_opening = _signed_amount(required=False, label="Wallet balance")
    categories = forms.MultipleChoiceField(
        choices=[(name, name) for name, _, _, _ in services.DEFAULT_CATEGORIES], required=False, label="Starter categories")
    monthly_budget = forms.DecimalField(max_digits=12, decimal_places=2, min_value=MIN_AMOUNT, max_value=MAX_AMOUNT,
                                        required=False, label="Monthly spending budget")
    sample_data = forms.BooleanField(required=False, label="Fill the app with sample data so I can look around")

    def __init__(self, *args, user, **kwargs):
        self.user = user
        profile = services.get_profile(user)
        kwargs.setdefault("initial", {
            "currency_code": profile.currency_code, "currency_symbol": profile.currency_symbol,
            "number_format": profile.number_format, "main_name": "Main account", "main_opening": 0,
            "categories": [name for name, _, _, _ in services.DEFAULT_CATEGORIES],
        })
        super().__init__(*args, **kwargs)

    clean_currency_code = SettingsForm.clean_currency_code
    clean_currency_symbol = SettingsForm.clean_currency_symbol

    def clean_main_name(self):
        return " ".join(self.cleaned_data["main_name"].split())

    def apply(self):
        d = self.cleaned_data
        profile = services.get_profile(self.user)
        profile.currency_code, profile.currency_symbol, profile.number_format = d["currency_code"], d["currency_symbol"], d["number_format"]
        profile.setup_done = True
        profile.save()
        with transaction.atomic():
            if d["sample_data"]:
                from . import backup, demo
                backup.erase(self.user)
                demo.seed_user(self.user)
            else:
                main = services.default_account(self.user)
                main.name, main.opening_balance = d["main_name"], d.get("main_opening") or services.ZERO
                main.save()
                if d["cash"]:
                    Account.objects.get_or_create(user=self.user, name__iexact="Cash",
                                                  defaults={"name": "Cash", "type": "cash", "opening_balance": d.get("cash_opening") or 0})
                if d["wallet"]:
                    Account.objects.get_or_create(user=self.user, name__iexact="Mobile wallet",
                                                  defaults={"name": "Mobile wallet", "type": "wallet", "opening_balance": d.get("wallet_opening") or 0})
                keep = set(d["categories"])
                Category.objects.filter(user=self.user, name__in=[n for n, *_ in services.DEFAULT_CATEGORIES if n not in keep],
                                        transactions__isnull=True).delete()
                if not Category.objects.filter(user=self.user).exists():
                    services.create_default_categories(self.user)
                if d.get("monthly_budget"):
                    today = timezone.localdate()
                    Budget.objects.update_or_create(user=self.user, category=None, month=today.replace(day=1),
                                                    defaults={"amount": d["monthly_budget"]})
        services.forget_profile(self.user)
