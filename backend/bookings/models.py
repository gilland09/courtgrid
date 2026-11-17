from decimal import Decimal
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from facilities.models import BookableResource, Sport


class UserProfile(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer / Player'
        COURT_OWNER = 'court_owner', 'Court Owner / Venue Partner'
        ADMIN = 'admin', 'Platform Administrator'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='courtgrid_profile',
    )
    phone_number = models.CharField(max_length=32, blank=True)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.CUSTOMER,
    )

    @property
    def user_role(self):
        if self.user.is_staff or self.user.is_superuser:
            return self.Role.ADMIN
        return self.role

    def __str__(self):
        return f'{self.user} profile'


def get_user_role(user):
    if not user.is_authenticated:
        return UserProfile.Role.CUSTOMER
    if user.is_staff or user.is_superuser:
        return UserProfile.Role.ADMIN
    try:
        return user.courtgrid_profile.user_role
    except UserProfile.DoesNotExist:
        return UserProfile.Role.CUSTOMER


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    class PaymentMethod(models.TextChoices):
        GCASH = 'gcash', 'GCash'
        MAYA = 'maya', 'Maya'
        CARD = 'card', 'Credit / Debit Card'
        CASH = 'cash', 'Pay at Venue'

    class PaymentStatus(models.TextChoices):
        PAID = 'paid', 'Paid'
        PENDING = 'pending', 'Pending'
        REFUNDED = 'refunded', 'Refunded'

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
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    rate_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    platform_fee_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal('0.0500'),
    )
    platform_fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    owner_payout_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    payment_method = models.CharField(
        max_length=24,
        choices=PaymentMethod.choices,
        default=PaymentMethod.GCASH,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PAID,
    )
    payment_reference = models.CharField(
        max_length=40,
        blank=True,
        default='',
        unique=True,
    )
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

    def save(self, *args, **kwargs):
        rate_snapshot = Decimal(str(self.rate_snapshot))
        total_price = Decimal(str(self.total_price or '0.00'))
        if not total_price and rate_snapshot:
            total_price = rate_snapshot
        self.rate_snapshot = rate_snapshot
        self.total_price = total_price
        self.platform_fee_rate = Decimal('0.0500')
        self.platform_fee_amount = (
            self.total_price * self.platform_fee_rate
        ).quantize(Decimal('0.01'))
        self.owner_payout_amount = (
            self.total_price - self.platform_fee_amount
        ).quantize(Decimal('0.01'))
        if not self.payment_reference:
            while True:
                reference = (
                    f"CG-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
                )
                if not type(self).objects.filter(
                    payment_reference=reference,
                ).exclude(pk=self.pk).exists():
                    self.payment_reference = reference
                    break
        self.payment_status = (
            self.PaymentStatus.PENDING
            if self.payment_method == self.PaymentMethod.CASH
            else self.PaymentStatus.PAID
        )

        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {
                'total_price',
                'platform_fee_rate',
                'platform_fee_amount',
                'owner_payout_amount',
                'payment_status',
                'payment_reference',
            }
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Booking {self.pk}: {self.resource} {self.start_datetime}'
