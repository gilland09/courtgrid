from django.urls import path

from .views import FacilityDetailView, FacilityListView, SportListView

urlpatterns = [
    path('sports/', SportListView.as_view(), name='sport-list'),
    path('facilities/', FacilityListView.as_view(), name='facility-list'),
    path('facilities/<int:pk>/', FacilityDetailView.as_view(), name='facility-detail'),
    path('courts/', FacilityListView.as_view(), name='court-list'),
    path('courts/<int:pk>/', FacilityDetailView.as_view(), name='court-detail'),
]
