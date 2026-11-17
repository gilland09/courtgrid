from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, UserProfile
from facilities.models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilitySport,
    Sport,
)


class UnifiedAuthenticationAndDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(
            username='frontend-member',
            password='member-test-password',
        )
        self.staff = user_model.objects.create_user(
            username='frontend-staff',
            password='staff-test-password',
            is_staff=True,
        )

    def test_root_displays_the_single_login_page(self):
        response = self.client.get(reverse('login'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertContains(response, reverse('register'))

    def test_registration_form_renders_for_anonymous_users(self):
        response = self.client.get(reverse('register'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')
        self.assertContains(response, 'Create a CourtGrid Account')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')

    def test_valid_registration_creates_and_logs_in_regular_user(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'new-courtgrid-user',
                'password1': 'Secure-demo-password-138!',
                'password2': 'Secure-demo-password-138!',
            },
        )

        user = get_user_model().objects.get(username='new-courtgrid-user')
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertFalse(user.is_staff)
        self.assertEqual(user.courtgrid_profile.role, UserProfile.Role.CUSTOMER)
        self.assertEqual(user.courtgrid_profile.user_role, UserProfile.Role.CUSTOMER)

    def test_registration_saves_contact_details_and_requires_terms_for_new_form(self):
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'Alex Courtgrid',
                'username': 'contact-courtgrid-user',
                'email': 'alex@example.com',
                'phone_number': '+639171234567',
                'password1': 'Secure-demo-password-138!',
                'password2': 'Secure-demo-password-138!',
                'accept_terms': 'on',
            },
        )

        self.assertRedirects(response, reverse('home'))
        user = get_user_model().objects.get(username='contact-courtgrid-user')
        self.assertEqual(user.first_name, 'Alex')
        self.assertEqual(user.last_name, 'Courtgrid')
        self.assertEqual(user.email, 'alex@example.com')
        self.assertEqual(user.courtgrid_profile.phone_number, '+639171234567')

        self.client.logout()
        response = self.client.post(
            reverse('register'),
            {
                'full_name': 'No Terms',
                'username': 'no-terms-user',
                'password1': 'Secure-demo-password-138!',
                'password2': 'Secure-demo-password-138!',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='no-terms-user').exists())

    def test_registration_can_choose_court_owner_role(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'new-court-owner',
                'account_type': UserProfile.Role.COURT_OWNER,
                'password1': 'Secure-demo-password-138!',
                'password2': 'Secure-demo-password-138!',
            },
        )

        self.assertRedirects(response, reverse('owner_dashboard'))
        owner = get_user_model().objects.get(username='new-court-owner')
        self.assertEqual(owner.courtgrid_profile.role, UserProfile.Role.COURT_OWNER)

    def test_invalid_registration_rerenders_form_without_creating_user(self):
        response = self.client.post(
            reverse('register'),
            {
                'username': 'invalid-registration',
                'password1': 'short',
                'password2': 'different',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'register.html')
        self.assertFalse(
            get_user_model().objects.filter(username='invalid-registration').exists()
        )

    def test_authenticated_user_cannot_open_registration_form(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('register'))

        self.assertRedirects(response, reverse('home'))

    def test_member_login_redirects_to_home(self):
        response = self.client.post(
            reverse('login'),
            {'username': self.member.username, 'password': 'member-test-password'},
        )

        self.assertRedirects(response, reverse('home'))
        self.assertEqual(int(self.client.session['_auth_user_id']), self.member.pk)

    def test_staff_login_redirects_to_protected_admin_dashboard(self):
        response = self.client.post(
            reverse('login'),
            {'username': self.staff.username, 'password': 'staff-test-password'},
            follow=True,
        )

        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertTemplateUsed(response, 'admin_dashboard.html')

    def test_authenticated_login_page_routes_by_role(self):
        self.client.force_login(self.member)
        member_response = self.client.get(reverse('login'))
        self.assertRedirects(member_response, reverse('home'))

        self.client.force_login(self.staff)
        staff_response = self.client.get(reverse('login'))
        self.assertRedirects(staff_response, reverse('admin_dashboard'))

    def test_admin_dashboard_requires_staff_access(self):
        anonymous_response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.member)
        member_response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(member_response.status_code, 302)
        self.assertIn(reverse('login'), member_response.url)

        self.client.force_login(self.staff)
        staff_response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(staff_response.status_code, 200)
        self.assertTemplateUsed(staff_response, 'admin_dashboard.html')

    def test_my_bookings_page_requires_login(self):
        response = self.client.get(reverse('my_bookings'))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('my_bookings')}",
        )

    def test_my_bookings_page_renders_for_authenticated_user(self):
        self.client.force_login(self.member)

        response = self.client.get(reverse('my_bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'my_bookings.html')
        self.assertContains(response, 'id="bookings-container"')
        self.assertContains(response, 'js/my_bookings.js')

    def test_logout_requires_post_and_returns_to_login(self):
        self.client.force_login(self.member)
        get_response = self.client.get(reverse('logout'))
        self.assertEqual(get_response.status_code, 405)

        post_response = self.client.post(reverse('logout'))

        self.assertRedirects(post_response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_home_includes_active_sports_for_discovery_filter(self):
        Sport.objects.create(name='Basketball', slug='basketball')
        Sport.objects.create(name='Inactive Sport', slug='inactive-sport', is_active=False)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
        self.assertContains(response, 'Basketball')
        self.assertNotContains(response, 'Inactive Sport')
        self.assertContains(response, 'id="map"')
        self.assertContains(response, 'id="facility-list"')


class AdminDashboardActivityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.staff = user_model.objects.create_user(
            username='activity-dashboard-admin',
            is_staff=True,
        )
        cls.member = user_model.objects.create_user(username='activity-dashboard-member')
        cls.sport = Sport.objects.create(name='Basketball', slug='dashboard-basketball')
        cls.facility = Facility.objects.create(name='Dashboard Facility')
        cls.facility_sport = FacilitySport.objects.create(
            facility=cls.facility,
            sport=cls.sport,
        )
        cls.resource = BookableResource.objects.create(
            facility=cls.facility,
            name='Main Court',
        )

    def test_dashboard_lists_today_confirmed_bookings_and_active_closures(self):
        now = timezone.now()
        local_now = timezone.localtime(now)
        booking_start = timezone.make_aware(
            datetime.combine(local_now.date(), time(hour=12)),
        )
        Booking.objects.create(
            user=self.member,
            resource=self.resource,
            sport=self.sport,
            start_datetime=booking_start,
            end_datetime=booking_start + timedelta(hours=1),
            participant_count=2,
            status=Booking.Status.CONFIRMED,
            rate_snapshot=Decimal('200.00'),
            total_price=Decimal('200.00'),
        )
        active_closure = FacilityClosure.objects.create(
            facility=self.facility,
            resource=self.resource,
            start_datetime=now - timedelta(minutes=30),
            end_datetime=now + timedelta(hours=2),
            reason='Maintenance',
        )
        FacilityClosure.objects.create(
            facility=self.facility,
            start_datetime=now + timedelta(hours=3),
            end_datetime=now + timedelta(hours=4),
            reason='Future closure',
        )

        self.client.force_login(self.staff)
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['todays_bookings']), 1)
        self.assertEqual(
            response.context['financial_totals']['gross'],
            Decimal('200.00'),
        )
        self.assertEqual(
            response.context['financial_totals']['platform_fee'],
            Decimal('10.00'),
        )
        self.assertEqual(
            response.context['financial_totals']['owner_payout'],
            Decimal('190.00'),
        )
        self.assertEqual(response.context['active_verified_venues'], 0)
        self.assertEqual(response.context['active_courts'], 0)
        self.assertEqual(
            response.context['active_closures'].get(),
            active_closure,
        )
        self.assertContains(response, 'Dashboard Facility')
        self.assertContains(response, 'Maintenance')
        self.assertContains(response, reverse('management_facilities'))
        self.assertContains(response, reverse('management_closures'))
        self.assertNotContains(response, 'href="/admin/"')
