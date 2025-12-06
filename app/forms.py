from captcha.fields import CaptchaField
from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Account, Category, Transaction


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent", "icon", "color"]


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ["name", "account_type", "opening_balance"]


class RegisterForm(UserCreationForm):
    email = forms.EmailField()
    full_name = forms.CharField(max_length=100, required=True)
    if settings.REQUIRE_CAPTCHA:
        captcha = CaptchaField()

        class Meta:
            model = User
            fields = [
                "full_name",
                "username",
                "email",
                "password1",
                "password2",
                "captcha",
            ]

    else:

        class Meta:
            model = User
            fields = ["full_name", "username", "email", "password1", "password2"]

    def save(self, commit=True):
        user = super(RegisterForm, self).save(commit=False)
        try:
            user.first_name, user.last_name = self.cleaned_data["full_name"].split(
                " ", 1
            )
        except ValueError:
            user.first_name = self.cleaned_data["full_name"]
            user.last_name = ""
        if commit:
            user.save()
        return user


class TransactionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields["category"].queryset = Category.objects.filter(user=user)
            self.fields["account"].queryset = Account.objects.filter(owner=user)
            self.fields["to_account"].queryset = Account.objects.filter(owner=user)

        for field_name, field in self.fields.items():
            if field_name not in ["remarks", "to_account", "attachment", "category"]:
                field.required = True

        self.fields["to_account"].required = False
        self.fields["category"].required = False

    class Meta:
        model = Transaction
        fields = [
            "name",
            "amount",
            "date",
            "transaction_type",
            "account",
            "to_account",
            "category",
            "remarks",
            "attachment",
        ]
        widgets = {
            "date": forms.TextInput(attrs={"type": "date"}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }


class TransactionUpdateForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = [
            "name",
            "amount",
            "date",
            "transaction_type",
            "account",
            "to_account",
            "category",
            "remarks",
            "attachment",
        ]
        widgets = {
            "date": forms.TextInput(attrs={"type": "date"}),
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        user = None
        if self.instance:
            user = self.instance.user

        if user:
            self.fields["account"].queryset = Account.objects.filter(owner=user)
            self.fields["to_account"].queryset = Account.objects.filter(owner=user)
            self.fields["category"].queryset = Category.objects.filter(user=user)

        for field_name, field in self.fields.items():
            if field_name not in ["remarks", "to_account", "attachment", "category"]:
                field.required = True

        self.fields["to_account"].required = False
        self.fields["category"].required = False
