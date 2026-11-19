from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase
from django.urls import reverse

from bookings.models import UserProfile
from config.middleware import _client_ip
from facilities.portal_forms import FacilityPayoutWalletForm


class RateLimitSecurityTests(TestCase):
    def setUp(self):
        self.rate_clock = patch('config.middleware.time.time', return_value=1_700_000_000)
        self.rate_clock.start()
        cache.clear()
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            username='security-customer',
            password='test-password',
        )
        self.owner = user_model.objects.create_user(
            username='security-owner',
            password='test-password',
        )
        UserProfile.objects.create(user=self.owner, role=UserProfile.Role.COURT_OWNER)

    def tearDown(self):
        self.rate_clock.stop()

    def test_registration_rate_limit_returns_retry_after(self):
        for attempt in range(5):
            response = self.client.post(
                reverse('register'),
                {
                    'username': f'limited-registration-{attempt}',
                    'password1': 'short',
                    'password2': 'different',
                },
            )
            self.assertNotEqual(response.status_code, 429)

        limited = self.client.post(
            reverse('register'),
            {'username': 'limited-registration-final'},
        )

        self.assertEqual(limited.status_code, 429)
        self.assertIn('Retry-After', limited)
        self.assertContains(limited, 'wait a moment', status_code=429)

    @patch('config.views.AuthenticationForm.is_valid', return_value=False)
    def test_login_limit_is_scoped_to_ip_and_username_pair(self, _is_valid):
        for _attempt in range(8):
            response = self.client.post(
                reverse('login'),
                {'username': 'target-account', 'password': 'incorrect'},
            )
            self.assertNotEqual(response.status_code, 429)

        limited = self.client.post(
            reverse('login'),
            {'username': 'target-account', 'password': 'incorrect'},
        )
        other_account = self.client.post(
            reverse('login'),
            {'username': 'different-account', 'password': 'incorrect'},
        )

        self.assertEqual(limited.status_code, 429)
        self.assertEqual(other_account.status_code, 200)
        self.assertIn('Retry-After', limited)

    def test_booking_rate_limit_returns_json_429(self):
        self.client.force_login(self.customer)
        for _attempt in range(15):
            response = self.client.post(
                '/api/bookings/',
                data='{}',
                content_type='application/json',
            )
            self.assertNotEqual(response.status_code, 429)

        limited = self.client.post(
            '/api/bookings/',
            data='{}',
            content_type='application/json',
        )

        self.assertEqual(limited.status_code, 429)
        self.assertIn('Retry-After', limited)
        self.assertEqual(limited.json()['detail'], 'Too many requests. Please try again shortly.')

    def test_owner_management_rate_limit_is_per_authenticated_user(self):
        self.client.force_login(self.owner)
        for _attempt in range(10):
            response = self.client.post(
                reverse('owner_dashboard'),
                {'action': 'save_facility'},
            )
            self.assertNotEqual(response.status_code, 429)

        limited = self.client.post(
            reverse('owner_dashboard'),
            {'action': 'save_facility'},
        )

        self.assertEqual(limited.status_code, 429)
        self.assertIn('Retry-After', limited)

    def test_availability_rate_limit_returns_json_429(self):
        for _attempt in range(60):
            response = self.client.get('/api/availability/search', {'date': 'invalid'})
            self.assertNotEqual(response.status_code, 429)

        limited = self.client.get('/api/availability/search', {'date': 'invalid'})

        self.assertEqual(limited.status_code, 429)
        self.assertIn('Retry-After', limited)
        self.assertEqual(limited.json()['detail'], 'Too many requests. Please try again shortly.')

    def test_forwarded_ip_is_ignored_unless_remote_peer_is_trusted(self):
        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='198.51.100.10',
            HTTP_X_FORWARDED_FOR='203.0.113.20',
        )
        self.assertEqual(_client_ip(request, ('10.0.0.0/8',)), '198.51.100.10')

        request = RequestFactory().get(
            '/',
            REMOTE_ADDR='10.1.2.3',
            HTTP_X_FORWARDED_FOR='203.0.113.20, 10.2.3.4',
        )
        self.assertEqual(_client_ip(request, ('10.0.0.0/8',)), '203.0.113.20')

    def test_qr_upload_rejects_executable_extension_and_oversize_file(self):
        invalid_extension = FacilityPayoutWalletForm(
            data={},
            files={
                'payment_qr_image': SimpleUploadedFile(
                    'merchant-qr.html',
                    b'\x89PNG\r\n\x1a\nnot-an-image',
                    content_type='image/png',
                ),
            },
        )
        oversized = FacilityPayoutWalletForm(
            data={},
            files={
                'payment_qr_image': SimpleUploadedFile(
                    'merchant-qr.png',
                    b'x' * (5 * 1024 * 1024 + 1),
                    content_type='image/png',
                ),
            },
        )

        self.assertFalse(invalid_extension.is_valid())
        self.assertIn('matching file type', str(invalid_extension.errors))
        self.assertFalse(oversized.is_valid())
        self.assertIn('5 MB or smaller', str(oversized.errors))
