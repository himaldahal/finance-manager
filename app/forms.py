from django import forms
from .models import *
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from captcha.fields import CaptchaField
from django.contrib.auth.forms import AuthenticationForm
from django.conf import settings

class TransactionTypeForm(forms.ModelForm):
    class Meta:
        model = TransactionType
        fields = ['name']

if settings.REQUIRE_CAPTCHA:
    class CustomAuthenticationForm(AuthenticationForm):
        captcha = CaptchaField()
else:
    class CustomAuthenticationForm(AuthenticationForm):
        pass

class RegisterForm(UserCreationForm):
    email = forms.EmailField()
    full_name = forms.CharField(max_length=100, required=True)
    if settings.REQUIRE_CAPTCHA:
      captcha = CaptchaField()
      class Meta:
            model = User
            fields = ["full_name", "username", "email", "password1", "password2", "captcha"]
    else:
         class Meta:
            model = User
            fields = ["full_name", "username", "email", "password1", "password2"]


    def save(self, commit=True):
        user = super(RegisterForm, self).save(commit=False)
        user.first_name, user.last_name = self.cleaned_data['full_name'].split(' ', 1)
        if commit:
            user.save()
        return user

class TransactionForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['category'].queryset = TransactionType.objects.filter(added_by=user)

        for field_name, field in self.fields.items():
            if field_name != 'remarks':
                field.required = True

    class Meta:
        model = Transaction
        fields = ['name', 'amount', 'date', 'transaction_type', 'category', 'remarks']
        widgets = {
            'date': forms.TextInput(attrs={'type': 'date'}),
            'remarks': forms.Textarea(attrs={'rows': 2}),
        }

class TransactionUpdateForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['name', 'amount', 'date', 'transaction_type', 'category', 'remarks']
        widgets = {
            'date': forms.TextInput(attrs={'type': 'date'}),
            'remarks': forms.Textarea(attrs={'rows': 2}),
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        for field_name, field in self.fields.items():
            if field_name != 'remarks':
                field.required = True
