from django import forms
from django.db.models import Q

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
)


class FacilityForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['is_active'].widget.attrs['class'] = 'form-check-input'

    class Meta:
        model = Facility
        fields = (
            'name',
            'barangay',
            'address',
            'latitude',
            'longitude',
            'capacity',
            'is_active',
        )
        widgets = {
            'latitude': forms.NumberInput(attrs={'step': '0.000001'}),
            'longitude': forms.NumberInput(attrs={'step': '0.000001'}),
        }


class AdminFacilityForm(FacilityForm):
    class Meta(FacilityForm.Meta):
        fields = FacilityForm.Meta.fields + ('is_verified',)


class BookableResourceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['is_active'].widget.attrs['class'] = 'form-check-input'

    class Meta:
        model = BookableResource
        fields = ('name', 'capacity', 'is_active')


class FacilitySportForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['is_active'].widget.attrs['class'] = 'form-check-input'

    class Meta:
        model = FacilitySport
        fields = ('hourly_rate', 'is_active')


class FacilityPayoutWalletForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = (
            'wallet_account_name',
            'gcash_number',
            'maya_number',
            'accepts_card',
            'payout_qr_label',
            'payment_qr_image',
        )
        widgets = {
            'wallet_account_name': forms.TextInput(attrs={'autocomplete': 'organization'}),
            'gcash_number': forms.TextInput(attrs={'autocomplete': 'off', 'inputmode': 'tel'}),
            'maya_number': forms.TextInput(attrs={'autocomplete': 'off', 'inputmode': 'tel'}),
            'payout_qr_label': forms.TextInput(),
            'payment_qr_image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }
        labels = {
            'accepts_card': 'Accept card payments arranged directly with the venue',
        }
        help_texts = {
            'accepts_card': (
                'CourtGrid does not process card payments; customers coordinate '
                'payment with your venue.'
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['accepts_card'].widget.attrs['class'] = 'form-check-input'

    def clean_payment_qr_image(self):
        uploaded = self.cleaned_data.get('payment_qr_image')
        if not uploaded or not hasattr(uploaded, 'read'):
            return uploaded
        signature = uploaded.read(12)
        uploaded.seek(0)
        valid_signatures = (
            signature.startswith(b'\x89PNG\r\n\x1a\n'),
            signature.startswith(b'\xff\xd8\xff'),
            signature.startswith((b'GIF87a', b'GIF89a')),
            signature[:4] == b'RIFF' and signature[8:12] == b'WEBP',
        )
        if not any(valid_signatures):
            raise forms.ValidationError('Upload a PNG, JPEG, GIF, or WebP QR image.')
        return uploaded


class FacilityOperatingHoursForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')

    class Meta:
        model = FacilityOperatingHours
        fields = ('day_of_week', 'start_time', 'end_time')
        widgets = {
            'start_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'end_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
        }


class FacilityClosureForm(forms.ModelForm):
    class Meta:
        model = FacilityClosure
        fields = ('facility', 'resource', 'start_datetime', 'end_datetime', 'reason')
        widgets = {
            'start_datetime': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
            'end_datetime': forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local'},
            ),
        }

    def __init__(self, *args, facilities=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')
        if facilities is not None:
            self.fields['facility'].queryset = facilities
            self.fields['resource'].queryset = BookableResource.objects.filter(
                facility__in=facilities,
            )
        self.fields['resource'].required = False

    def clean(self):
        cleaned_data = super().clean()
        facility = cleaned_data.get('facility')
        resource = cleaned_data.get('resource')
        start_datetime = cleaned_data.get('start_datetime')
        end_datetime = cleaned_data.get('end_datetime')
        if facility and resource and resource.facility_id != facility.pk:
            self.add_error('resource', 'Select a court belonging to this facility.')
        if facility and start_datetime and end_datetime:
            overlaps = FacilityClosure.objects.filter(
                facility=facility,
                start_datetime__lt=end_datetime,
                end_datetime__gt=start_datetime,
            )
            overlaps = overlaps.filter(
                Q(resource__isnull=True) | Q(resource=resource)
                if resource
                else Q()
            )
            if self.instance.pk:
                overlaps = overlaps.exclude(pk=self.instance.pk)
            if overlaps.exists():
                self.add_error(
                    None,
                    'This closure overlaps an existing closure for the selected court or facility.',
                )
        return cleaned_data
