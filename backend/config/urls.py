"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from facilities.management_views import (
    management_closures_view,
    management_facilities_view,
    owner_dashboard_view,
)
from facilities.views import facility_detail_view

from .views import (
    admin_cancel_booking,
    admin_dashboard_view,
    admin_delete_all_logs,
    admin_delete_log,
    home_view,
    login_view,
    logout_view,
    my_bookings_view,
    register_view,
    settle_commission_view,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', login_view, name='login'),
    path('register/', register_view, name='register'),
    path('home/', home_view, name='home'),
    path('my-bookings/', my_bookings_view, name='my_bookings'),
    path(
        'facilities/<int:pk>/',
        facility_detail_view,
        name='facility-detail-page',
    ),
    path('admin-dashboard/', admin_dashboard_view, name='admin_dashboard'),
    path(
        'admin-dashboard/commissions/<int:booking_id>/settle/',
        settle_commission_view,
        name='settle_commission',
    ),
    path(
        'admin-dashboard/bookings/<int:booking_id>/cancel/',
        admin_cancel_booking,
        name='admin_cancel_booking',
    ),
    path(
        'admin-dashboard/logs/<int:log_id>/delete/',
        admin_delete_log,
        name='admin_delete_log',
    ),
    path(
        'admin-dashboard/logs/delete-all/',
        admin_delete_all_logs,
        name='admin_delete_all_logs',
    ),
    path('owner/dashboard/', owner_dashboard_view, name='owner_dashboard'),
    path('management/facilities/', management_facilities_view, name='management_facilities'),
    path('management/closures/', management_closures_view, name='management_closures'),
    path('logout/', logout_view, name='logout'),
    path('api/', include('facilities.urls')),
    path('api/', include('bookings.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
