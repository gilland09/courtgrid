from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q


STANDARD_AMENITIES = (
    'Covered Roof',
    'Floodlights',
    'Free Parking',
    'Restrooms',
    'Drinking Water',
    'Bleachers / Seating',
    'Equipment Rental',
    'Locker / Changing Area',
    'Wi-Fi',
    'Air-Conditioned',
    'Canteen / Refreshments',
    'First Aid Kit',
)


class Sport(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name


class Facility(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Verification'
        VERIFIED = 'verified', 'Verified'
        REJECTED = 'rejected', 'Rejected'

    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='owned_facilities',
        null=True,
        blank=True,
    )
    gcash_number = models.CharField(max_length=20, blank=True, default='')
    maya_number = models.CharField(max_length=20, blank=True, default='')
    accepts_card = models.BooleanField(
        default=False,
        help_text='Accept card payments arranged directly with the venue.',
    )
    wallet_account_name = models.CharField(max_length=120, blank=True, default='')
    payout_qr_label = models.CharField(max_length=120, blank=True, default='')
    payment_qr_image = models.FileField(
        upload_to='owner_qrs/',
        blank=True,
        null=True,
    )
    address = models.TextField(blank=True)
    barangay = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    facility_type = models.CharField(max_length=50, blank=True)
    business_trade_name = models.CharField(max_length=200, blank=True, default='')
    business_permit_no = models.CharField(max_length=100, blank=True, default='')
    business_contact_number = models.CharField(max_length=32, blank=True, default='')
    dpa_consent_accepted = models.BooleanField(default=False)
    dpa_consent_accepted_at = models.DateTimeField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    capacity = models.PositiveIntegerField(null=True, blank=True)
    default_hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    amenities = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_demo_data = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=False)
    data_source = models.CharField(max_length=255, blank=True)
    verified_by = models.CharField(max_length=150, blank=True)
    verification_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ('name',)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True, longitude__isnull=True)
                    | Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name='facility_coordinates_both_null_or_set',
            ),
        ]

    def __str__(self):
        return self.name

    def ensure_default_court(self):
        existing_court = self.resources.order_by('display_order', 'pk').first()
        if existing_court is not None:
            return existing_court
        return self.resources.get_or_create(
            name='Court 1',
            defaults={
                'resource_type': 'Court',
                'capacity': self.capacity,
            },
        )[0]

    @property
    def available_payment_methods(self):
        methods = []
        if self.gcash_number.strip():
            methods.append('gcash')
        if self.maya_number.strip():
            methods.append('maya')
        if self.accepts_card:
            methods.append('card')
        methods.append('cash')
        return methods


class FacilitySport(models.Model):
    facility = models.ForeignKey(
        Facility,
        on_delete=models.PROTECT,
        related_name='facility_sports',
    )
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name='facility_sports',
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text='Sport-specific PHP rate per one-hour slot; blank uses the facility default.',
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ('facility__name', 'sport__name')
        constraints = [
            models.UniqueConstraint(
                fields=('facility', 'sport'),
                name='unique_facility_sport',
            ),
        ]

    def __str__(self):
        return f'{self.facility}: {self.sport}'


class BookableResource(models.Model):
    facility = models.ForeignKey(
        Facility,
        on_delete=models.PROTECT,
        related_name='resources',
    )
    name = models.CharField(max_length=150)
    resource_type = models.CharField(max_length=50, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    sports = models.ManyToManyField(
        FacilitySport,
        through='ResourceSport',
        related_name='resources',
        blank=True,
    )

    class Meta:
        ordering = ('facility__name', 'name')
        constraints = [
            models.UniqueConstraint(
                fields=('facility', 'name'),
                name='unique_resource_name_per_facility',
            ),
        ]

    def __str__(self):
        return f'{self.facility} - {self.name}'

    @property
    def effective_hourly_rate(self):
        if self.hourly_rate is not None:
            return self.hourly_rate
        return self.facility.default_hourly_rate

    def effective_hourly_rate_for(self, facility_sport):
        if self.hourly_rate is not None:
            return self.hourly_rate
        if facility_sport.hourly_rate is not None:
            return facility_sport.hourly_rate
        return self.facility.default_hourly_rate


class FacilityPhoto(models.Model):
    class Category(models.TextChoices):
        COURT = 'court', 'Court'
        AMENITY = 'amenity', 'Amenity'
        EXTERIOR = 'exterior', 'Venue / Exterior'

    facility = models.ForeignKey(
        Facility,
        on_delete=models.CASCADE,
        related_name='photos',
    )
    image = models.FileField(upload_to='facility_photos/')
    caption = models.CharField(max_length=140, blank=True)
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.COURT,
    )
    is_cover = models.BooleanField(default=False)
    display_order = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('display_order', 'pk')
        constraints = [
            models.UniqueConstraint(
                fields=('facility',),
                condition=Q(is_cover=True),
                name='unique_facility_cover_photo',
            ),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Facility.objects.select_for_update().get(pk=self.facility_id)
            if not self.pk and not self.is_cover:
                self.is_cover = not type(self).objects.filter(
                    facility_id=self.facility_id,
                ).exists()
            if self.is_cover:
                type(self).objects.filter(
                    facility_id=self.facility_id,
                ).exclude(pk=self.pk).update(is_cover=False)
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            Facility.objects.select_for_update().get(pk=self.facility_id)
            was_cover = self.is_cover
            result = super().delete(*args, **kwargs)
            if was_cover:
                next_photo = type(self).objects.filter(
                    facility_id=self.facility_id,
                ).order_by('display_order', 'pk').first()
                if next_photo is not None:
                    next_photo.is_cover = True
                    next_photo.save(update_fields=('is_cover',))
            return result


class ResourceSport(models.Model):
    resource = models.ForeignKey(
        BookableResource,
        on_delete=models.CASCADE,
        related_name='resource_sports',
    )
    facility_sport = models.ForeignKey(
        FacilitySport,
        on_delete=models.PROTECT,
        related_name='resource_sports',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('resource', 'facility_sport'),
                name='unique_sport_per_resource',
            ),
        ]
        ordering = ('resource__name', 'facility_sport__sport__name')

    def __str__(self):
        return f'{self.resource}: {self.facility_sport.sport}'


class FacilityOperatingHours(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    facility = models.ForeignKey(
        Facility,
        on_delete=models.CASCADE,
        related_name='operating_hours',
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ('facility__name', 'day_of_week', 'start_time')
        constraints = [
            models.CheckConstraint(
                condition=Q(start_time__lt=F('end_time')),
                name='operating_hours_start_before_end',
            ),
            models.CheckConstraint(
                condition=(
                    Q(effective_from__isnull=True)
                    | Q(effective_until__isnull=True)
                    | Q(effective_from__lte=F('effective_until'))
                ),
                name='operating_hours_effective_dates_ordered',
            ),
        ]

    def __str__(self):
        return f'{self.facility} {self.get_day_of_week_display()} {self.start_time}-{self.end_time}'


class SportSchedule(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Monday'
        TUESDAY = 1, 'Tuesday'
        WEDNESDAY = 2, 'Wednesday'
        THURSDAY = 3, 'Thursday'
        FRIDAY = 4, 'Friday'
        SATURDAY = 5, 'Saturday'
        SUNDAY = 6, 'Sunday'

    facility_sport = models.ForeignKey(
        FacilitySport,
        on_delete=models.CASCADE,
        related_name='schedules',
    )
    resource = models.ForeignKey(
        BookableResource,
        on_delete=models.CASCADE,
        related_name='sport_schedules',
        null=True,
        blank=True,
        help_text='Blank applies to all eligible resources for this facility/sport.',
    )
    day_of_week = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    effective_from = models.DateField(null=True, blank=True)
    effective_until = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ('facility_sport__facility__name', 'day_of_week', 'start_time')
        constraints = [
            models.CheckConstraint(
                condition=Q(start_time__lt=F('end_time')),
                name='sport_schedule_start_before_end',
            ),
            models.CheckConstraint(
                condition=(
                    Q(effective_from__isnull=True)
                    | Q(effective_until__isnull=True)
                    | Q(effective_from__lte=F('effective_until'))
                ),
                name='sport_schedule_effective_dates_ordered',
            ),
        ]

    def __str__(self):
        return (
            f'{self.facility_sport} {self.get_day_of_week_display()} '
            f'{self.start_time}-{self.end_time}'
        )


class FacilityClosure(models.Model):
    facility = models.ForeignKey(
        Facility,
        on_delete=models.CASCADE,
        related_name='closures',
    )
    resource = models.ForeignKey(
        BookableResource,
        on_delete=models.CASCADE,
        related_name='closures',
        null=True,
        blank=True,
        help_text='Blank applies to the whole facility.',
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    reason = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='facility_closures_created',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('start_datetime',)
        constraints = [
            models.CheckConstraint(
                condition=Q(start_datetime__lt=F('end_datetime')),
                name='facility_closure_start_before_end',
            ),
        ]

    def __str__(self):
        return f'{self.facility} closure: {self.start_datetime}'
