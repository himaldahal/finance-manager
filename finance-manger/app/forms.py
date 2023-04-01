from django import forms
from .models import Transaction

class TransactionForm(forms.ModelForm):
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
