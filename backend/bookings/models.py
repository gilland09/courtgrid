from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from facilities.models import BookableResource, Sport


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='courtgrid_profile',
    )
    phone_number = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return f'{self.user} profile'


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='court_bookings',
    )
    resource = models.ForeignKey(
        BookableResource,
        on_delete=models.PROTECT,
        related_name='bookings',
    )
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name='bookings',
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    participant_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    participant_names = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    rate_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='PHP')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-start_datetime',)
        constraints = [
            models.CheckConstraint(
                condition=Q(start_datetime__lt=F('end_datetime')),
                name='booking_start_before_end',
            ),
            models.CheckConstraint(
                condition=Q(participant_count__gte=1),
                name='booking_participant_count_positive',
            ),
            models.CheckConstraint(
                condition=Q(rate_snapshot__gte=0),
                name='booking_rate_snapshot_nonnegative',
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0),
                name='booking_total_price_nonnegative',
            ),
        ]

    def __str__(self):
        return f'Booking {self.pk}: {self.resource} {self.start_datetime}'
