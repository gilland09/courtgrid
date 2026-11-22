from pathlib import PurePath
import struct
import zlib

from django import forms
from django.db.models import Q

from .models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilityPhoto,
    FacilitySport,
    Sport,
    STANDARD_AMENITIES,
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


class CourtManagementForm(forms.ModelForm):
    sports = forms.ModelMultipleChoiceField(
        queryset=FacilitySport.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label='Sports available on this court',
    )

    def __init__(self, *args, facility, **kwargs):
        self.facility = facility
        super().__init__(*args, **kwargs)
        self.fields['sports'].queryset = facility.facility_sports.select_related(
            'sport',
        )
        self.fields['sports'].label_from_instance = lambda item: item.sport.name
        if self.instance.pk and not self.is_bound:
            self.initial['sports'] = self.instance.sports.values_list(
                'pk',
                flat=True,
            )
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                continue
            field.widget.attrs.setdefault('class', 'form-control')

    class Meta:
        model = BookableResource
        fields = ('name', 'capacity', 'hourly_rate', 'display_order')
        widgets = {
            'capacity': forms.NumberInput(attrs={'min': 1}),
            'hourly_rate': forms.NumberInput(attrs={'min': 0, 'step': '0.01'}),
            'display_order': forms.NumberInput(attrs={'min': 0}),
        }


class FacilityPhotoForm(forms.ModelForm):
    image = forms.FileField(
        widget=forms.ClearableFileInput(attrs={
            'accept': '.jpg,.jpeg,.png,.webp',
        }),
    )

    class Meta:
        model = FacilityPhoto
        fields = ('image', 'caption', 'category', 'is_cover')
        widgets = {
            'caption': forms.TextInput(attrs={'maxlength': 140}),
            'is_cover': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != 'is_cover':
                field.widget.attrs.setdefault('class', 'form-control')

    def clean_image(self):
        uploaded = self.cleaned_data['image']
        extension = PurePath(uploaded.name).suffix.lower()
        validators = {
            '.png': ImageContentValidator.valid_png,
            '.jpg': ImageContentValidator.valid_jpeg,
            '.jpeg': ImageContentValidator.valid_jpeg,
            '.webp': ImageContentValidator.valid_webp,
        }
        validator = validators.get(extension)
        if validator is None:
            raise forms.ValidationError(
                'Upload a JPG, JPEG, PNG, or WebP image.',
            )
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError('The image must be 5 MB or smaller.')
        try:
            content = uploaded.read(5 * 1024 * 1024 + 1)
        finally:
            uploaded.seek(0)
        if len(content) > 5 * 1024 * 1024 or not validator(content):
            raise forms.ValidationError(
                'The uploaded file is not a valid image matching its extension.',
            )
        return uploaded


class FacilityAmenitiesForm(forms.Form):
    amenities = forms.MultipleChoiceField(
        choices=tuple((item, item) for item in STANDARD_AMENITIES),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    custom_amenities = forms.CharField(
        required=False,
        max_length=1000,
        label='Custom amenities',
        help_text='Separate custom amenities with commas.',
    )

    def clean(self):
        cleaned_data = super().clean()
        selected = list(cleaned_data.get('amenities') or [])
        custom = cleaned_data.get('custom_amenities', '')
        amenity_names = selected + [
            item.strip()
            for item in custom.split(',')
            if item.strip()
        ]
        if any(len(item) > 60 for item in amenity_names):
            self.add_error(
                'custom_amenities',
                'Each amenity must be 60 characters or fewer.',
            )
            return cleaned_data

        deduplicated = []
        seen = set()
        for item in amenity_names:
            normalized = item.casefold()
            if normalized not in seen:
                deduplicated.append(item)
                seen.add(normalized)
        if len(deduplicated) > 20:
            self.add_error(
                'custom_amenities',
                'A venue may list up to 20 amenities.',
            )
        cleaned_data['cleaned_amenities'] = deduplicated
        return cleaned_data


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
        if uploaded.size > 5 * 1024 * 1024:
            raise forms.ValidationError('The QR image must be 5 MB or smaller.')

        extension = PurePath(uploaded.name).suffix.lower()
        allowed_types = {
            '.png': ('image/png', ImageContentValidator.valid_png),
            '.jpg': ('image/jpeg', ImageContentValidator.valid_jpeg),
            '.jpeg': ('image/jpeg', ImageContentValidator.valid_jpeg),
            '.webp': ('image/webp', ImageContentValidator.valid_webp),
        }
        allowed = allowed_types.get(extension)
        if allowed is None or uploaded.content_type != allowed[0]:
            raise forms.ValidationError(
                'Upload a PNG, JPEG, or WebP QR image with a matching file type.'
            )
        content = uploaded.read(5 * 1024 * 1024 + 1)
        uploaded.seek(0)
        if len(content) > 5 * 1024 * 1024 or not allowed[1](content):
            raise forms.ValidationError('The uploaded file is not a valid supported QR image.')
        return uploaded


class ImageContentValidator:
    @staticmethod
    def valid_png(content):
        if not content.startswith(b'\x89PNG\r\n\x1a\n'):
            return False
        offset = 8
        saw_header = False
        while offset + 12 <= len(content):
            chunk_length = struct.unpack_from('>I', content, offset)[0]
            chunk_end = offset + 12 + chunk_length
            if chunk_end > len(content):
                return False
            chunk_type = content[offset + 4:offset + 8]
            chunk_data = content[offset + 8:offset + 8 + chunk_length]
            expected_crc = struct.unpack_from('>I', content, offset + 8 + chunk_length)[0]
            if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != expected_crc:
                return False
            if not saw_header:
                if chunk_type != b'IHDR' or chunk_length != 13:
                    return False
                width, height = struct.unpack_from('>II', chunk_data)
                if width < 1 or height < 1 or width * height > 16_000_000:
                    return False
                saw_header = True
            if chunk_type == b'IEND':
                return saw_header and chunk_length == 0 and chunk_end == len(content)
            offset = chunk_end
        return False

    @staticmethod
    def valid_jpeg(content):
        if (
            len(content) < 4
            or not content.startswith(b'\xff\xd8')
            or not content.endswith(b'\xff\xd9')
        ):
            return False
        offset = 2
        found_dimensions = False
        while offset < len(content) - 2:
            if content[offset] != 0xFF:
                return False
            while offset < len(content) and content[offset] == 0xFF:
                offset += 1
            if offset >= len(content):
                return False
            marker = content[offset]
            offset += 1
            if marker == 0xDA:
                if offset + 2 > len(content):
                    return False
                segment_length = struct.unpack_from('>H', content, offset)[0]
                return (
                    found_dimensions
                    and segment_length >= 6
                    and offset + segment_length < len(content) - 2
                )
            if marker in {0xD8, 0xD9, 0x01, *range(0xD0, 0xD8)}:
                continue
            if offset + 2 > len(content):
                return False
            segment_length = struct.unpack_from('>H', content, offset)[0]
            segment_end = offset + segment_length
            if segment_length < 2 or segment_end > len(content):
                return False
            if marker in {
                0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
            }:
                if segment_length < 8:
                    return False
                height, width = struct.unpack_from('>HH', content, offset + 3)
                if width < 1 or height < 1 or width * height > 16_000_000:
                    return False
                found_dimensions = True
            offset = segment_end
        return False

    @staticmethod
    def valid_webp(content):
        if (
            len(content) < 20
            or content[:4] != b'RIFF'
            or content[8:12] != b'WEBP'
            or struct.unpack_from('<I', content, 4)[0] + 8 != len(content)
        ):
            return False
        offset = 12
        has_image_chunk = False
        while offset + 8 <= len(content):
            chunk_type = content[offset:offset + 4]
            chunk_length = struct.unpack_from('<I', content, offset + 4)[0]
            chunk_end = offset + 8 + chunk_length + (chunk_length % 2)
            if chunk_end > len(content):
                return False
            has_image_chunk |= chunk_type in {b'VP8 ', b'VP8L', b'VP8X'}
            offset = chunk_end
        return has_image_chunk and offset == len(content)


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
