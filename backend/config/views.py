from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from facilities.models import Sport


def _dashboard_url(user):
    return 'admin_dashboard' if user.is_staff else 'home'


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_dashboard_url(request.user))

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        auth_login(request, user)
        return redirect(_dashboard_url(user))

    return render(request, 'login.html', {'form': form})


@require_POST
def logout_view(request):
    auth_logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('login')


def home_view(request):
    sports = Sport.objects.filter(is_active=True).order_by('name')
    return render(request, 'home.html', {'sports': sports})


@staff_member_required(login_url='login')
def admin_dashboard_view(request):
    return render(request, 'admin_dashboard.html')
