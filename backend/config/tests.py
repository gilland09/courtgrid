from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from facilities.models import Sport


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
