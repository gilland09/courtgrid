import json
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / 'backend'
sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django

django.setup()

from django.db import transaction
from django.utils import timezone

from facilities.availability import evaluate_serial_availability
from facilities.availability_client import fetch_parallel_availability
from facilities.models import (
    BookableResource,
    Facility,
    FacilityClosure,
    FacilityOperatingHours,
    FacilitySport,
    ResourceSport,
    Sport,
    SportSchedule,
)


class _RollbackBenchmarkData(Exception):
    pass


def _slot_key(slot):
    return (
        slot['facility_id'],
        slot['resource_id'],
        slot['sport_id'],
        slot['start_datetime'].isoformat()
        if hasattr(slot['start_datetime'], 'isoformat')
        else slot['start_datetime'],
        slot['end_datetime'].isoformat()
        if hasattr(slot['end_datetime'], 'isoformat')
        else slot['end_datetime'],
    )


def run_benchmark():
    identifier = uuid.uuid4().hex[:12]
    target_date = timezone.localdate() + timedelta(days=1)
    day_of_week = target_date.weekday()
    app_tz = ZoneInfo(timezone.get_current_timezone_name())

    try:
        with transaction.atomic():
            sport = Sport.objects.create(
                name=f'Synthetic Benchmark Sport {identifier}',
                slug=f'benchmark-{identifier}',
            )
            facilities = []
            for index in range(10):
                facility = Facility.objects.create(
                    name=f'Synthetic Benchmark Facility {identifier}-{index:02d}',
                    is_demo_data=True,
                )
                facility_sport = FacilitySport.objects.create(
                    facility=facility,
                    sport=sport,
                    hourly_rate='100.00',
                )
                resource = BookableResource.objects.create(
                    facility=facility,
                    name=f'Synthetic Benchmark Court {index:02d}',
                    is_active=True,
                )
                ResourceSport.objects.create(
                    resource=resource,
                    facility_sport=facility_sport,
                )
                FacilityOperatingHours.objects.create(
                    facility=facility,
                    day_of_week=day_of_week,
                    start_time=datetime_time(8),
                    end_time=datetime_time(18),
                )
                SportSchedule.objects.create(
                    facility_sport=facility_sport,
                    day_of_week=day_of_week,
                    start_time=datetime_time(9),
                    end_time=datetime_time(17),
                )
                FacilityClosure.objects.create(
                    facility=facility,
                    resource=resource,
                    start_datetime=timezone.make_aware(
                        datetime.combine(target_date, datetime_time(12)),
                        app_tz,
                    ),
                    end_datetime=timezone.make_aware(
                        datetime.combine(target_date, datetime_time(13)),
                        app_tz,
                    ),
                    reason='Synthetic benchmark closure',
                )
                facilities.append(facility)

            offerings = list(
                FacilitySport.objects.filter(
                    facility__in=facilities,
                    sport=sport,
                    is_active=True,
                ).select_related('facility', 'sport')
            )
            closures = list(
                FacilityClosure.objects.filter(facility__in=facilities).select_related(
                    'facility',
                    'resource',
                )
            )
            schedules = list(
                SportSchedule.objects.filter(
                    facility_sport__in=offerings,
                ).select_related('facility_sport__facility', 'facility_sport__sport')
            )
            confirmed_bookings = []

            serial_samples = []
            parallel_samples = []
            serial_slots = None
            parallel_slots = None

            for _iteration in range(10):
                started = time.perf_counter()
                serial_slots = evaluate_serial_availability(offerings, target_date)
                serial_samples.append(time.perf_counter() - started)

            for _iteration in range(10):
                started = time.perf_counter()
                response = fetch_parallel_availability(
                    target_date=target_date,
                    facilities=facilities,
                    closures=closures,
                    schedules=schedules,
                    existing_bookings=confirmed_bookings,
                )
                parallel_samples.append(time.perf_counter() - started)
                parallel_slots = response['available_slots']

            serial_median = statistics.median(serial_samples)
            parallel_median = statistics.median(parallel_samples)
            speedup = serial_median / parallel_median if parallel_median else None

            serial_keys = sorted(_slot_key(slot) for slot in serial_slots)
            parallel_keys = sorted(_slot_key(slot) for slot in parallel_slots)
            if serial_keys != parallel_keys:
                raise RuntimeError(
                    'Serial and parallel result sets differ; benchmark cannot report speedup.'
                )

            print(json.dumps({
                'synthetic': True,
                'facility_count': len(facilities),
                'resource_count': len(facilities),
                'iterations_per_mode': 10,
                'available_slot_count': len(serial_slots),
                'serial_median_seconds': serial_median,
                'parallel_http_median_seconds': parallel_median,
                'speedup': speedup,
                'serial_parallel_results_equal': True,
                'data_cleanup': 'all synthetic records rolled back',
            }, indent=2))
            raise _RollbackBenchmarkData
    except _RollbackBenchmarkData:
        return


if __name__ == '__main__':
    run_benchmark()
