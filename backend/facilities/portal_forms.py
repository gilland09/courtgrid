from django import forms
from django.db.models import Q

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
    Sport,
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
            'business_trade_name',
            'business_permit_no',
            'business_contact_number',
            'is_active',
        )
        widgets = {
            'latitude': forms.NumberInput(attrs={'step': '0.000001'}),
            'longitude': forms.NumberInput(attrs={'step': '0.000001'}),
        }


class FacilityOnboardingForm(forms.Form):
    SPORTS = ('basketball', 'volleyball', 'pickleball')

    name = forms.CharField(max_length=200, label='Facility name')
    barangay = forms.CharField(
        max_length=100,
        label='Barangay',
        help_text='Barangay in Naval, Biliran.',
    )
    address = forms.CharField(
        label='Street / venue address',
        widget=forms.Textarea(attrs={'rows': 2}),
    )
    latitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        initial='11.5601',
        widget=forms.NumberInput(attrs={'step': '0.000001'}),
    )
    longitude = forms.DecimalField(
        max_digits=9,
        decimal_places=6,
        initial='124.3949',
        widget=forms.NumberInput(attrs={'step': '0.000001'}),
    )
    sports = forms.ModelMultipleChoiceField(
        queryset=Sport.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label='Sports offered',
    )
    court_count = forms.IntegerField(min_value=1, max_value=30, initial=1)
    basketball_rate = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        label='Basketball hourly rate (₱/hr)',
    )
    volleyball_rate = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        label='Volleyball hourly rate (₱/hr)',
    )
    pickleball_rate = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        required=False,
        label='Pickleball hourly rate (₱/hr)',
    )
    business_trade_name = forms.CharField(max_length=200, label='Business trade name')
    business_permit_no = forms.CharField(
        max_length=100,
        label='DTI/SEC registration or Barangay Business Permit number',
    )
    business_contact_number = forms.CharField(
        max_length=32,
        label='Official business contact number',
        widget=forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel'}),
    )
    dpa_consent_accepted = forms.BooleanField(
        required=True,
        label=(
            'I consent to CourtGrid collecting and securely processing the '
            'business and contact information submitted here, solely for venue '
            'verification and booking coordination, in accordance with Republic '
            'Act No. 10173 (Data Privacy Act of 2012).'
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sports'].queryset = Sport.objects.filter(
            is_active=True,
            slug__in=self.SPORTS,
        ).order_by('name')
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                continue
            field.widget.attrs.setdefault('class', 'form-control')
        self.fields['dpa_consent_accepted'].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        cleaned_data = super().clean()
        selected_sports = cleaned_data.get('sports', ())
        for sport in selected_sports:
            rate = cleaned_data.get(f'{sport.slug}_rate')
            if rate is None:
                self.add_error(
                    f'{sport.slug}_rate',
                    'Enter an hourly rate for each selected sport.',
                )
        return cleaned_data


class AdminFacilityForm(FacilityForm):
    pass


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
