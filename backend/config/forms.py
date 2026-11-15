from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from bookings.models import UserProfile


class RegistrationForm(UserCreationForm):
    full_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    phone_number = forms.CharField(max_length=32, required=False)
    accept_terms = forms.BooleanField(required=False)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username',)

    def clean(self):
        cleaned_data = super().clean()
        modern_fields_submitted = any(
            field in self.data
            for field in ('full_name', 'email', 'phone_number')
        )
        if modern_fields_submitted and not cleaned_data.get('accept_terms'):
            self.add_error('accept_terms', 'Please agree to the CourtGrid terms and court rules.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = self.cleaned_data.get('full_name', '').strip()
        first_name, separator, last_name = full_name.partition(' ')
        user.first_name = first_name
        user.last_name = last_name.strip() if separator else ''
        user.email = self.cleaned_data.get('email', '').strip()
        if commit:
            user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={'phone_number': self.cleaned_data.get('phone_number', '').strip()},
            )
        return user
