from django.db.models import Count, Prefetch, Q
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response

from .models import BookableResource, Facility, FacilitySport, Sport
from .serializers import FacilitySerializer, SportSerializer


class FacilityDiscoveryQuerysetMixin:
    def get_match_mode(self):
        match = self.request.query_params.get('match', 'any').strip().lower()
        if match not in {'any', 'all'}:
            raise ValidationError({'match': 'Use either "any" or "all".'})
        return match

    def get_requested_sports(self):
        return list(dict.fromkeys(
            slug.strip().lower()
            for slug in self.request.query_params.get('sports', '').split(',')
            if slug.strip()
        ))

    def get_facility_queryset(self, apply_sport_filter=True):
        active_facility_sports = FacilitySport.objects.filter(
            is_active=True,
            sport__is_active=True,
        ).select_related('sport')
        queryset = Facility.objects.filter(is_active=True).prefetch_related(
            Prefetch(
                'facility_sports',
                queryset=active_facility_sports,
                to_attr='active_facility_sports',
            ),
            Prefetch(
                'resources',
                queryset=BookableResource.objects.filter(is_active=True),
                to_attr='active_resources',
            ),
        )

        match = self.get_match_mode()
        sports = self.get_requested_sports()
        if not apply_sport_filter or not sports:
            return queryset

        supported_sport_filter = Q(
            facility_sports__is_active=True,
            facility_sports__sport__is_active=True,
        )
        if match == 'all':
            return (
                queryset.annotate(
                    _requested_sport_count=Count(
                        'facility_sports__sport',
                        filter=supported_sport_filter
                        & Q(facility_sports__sport__slug__in=sports),
                        distinct=True,
                    )
                )
                .filter(_requested_sport_count=len(sports))
            )
        return queryset.filter(
            supported_sport_filter,
            facility_sports__sport__slug__in=sports,
        ).distinct()


class SportListView(ListAPIView):
    serializer_class = SportSerializer
    queryset = Sport.objects.filter(is_active=True)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({'results': response.data})


class FacilityListView(FacilityDiscoveryQuerysetMixin, ListAPIView):
    serializer_class = FacilitySerializer

    def get_queryset(self):
        return self.get_facility_queryset()

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return Response({
            'results': response.data,
            'match': self.get_match_mode(),
        })


class FacilityDetailView(FacilityDiscoveryQuerysetMixin, RetrieveAPIView):
    serializer_class = FacilitySerializer

    def get_queryset(self):
        return self.get_facility_queryset(apply_sport_filter=False)
