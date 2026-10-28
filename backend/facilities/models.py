from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


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
    name = models.CharField(max_length=200)
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
    capacity = models.PositiveIntegerField(null=True, blank=True)
    default_hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
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
