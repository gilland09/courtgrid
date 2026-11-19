from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


APPLICATION_TIMEZONE = ZoneInfo('Asia/Manila')


class BoundaryModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ResourceData(BoundaryModel):
    resource_id: int
    facility_sport_ids: list[int] = Field(default_factory=list, max_length=50)


class OperatingHoursData(BoundaryModel):
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    effective_from: date | None = None
    effective_until: date | None = None


class FacilityData(BoundaryModel):
    facility_id: int
    resources: list[ResourceData] = Field(default_factory=list, max_length=50)
    operating_hours: list[OperatingHoursData] = Field(
        default_factory=list,
        max_length=100,
    )


class ScheduleData(BoundaryModel):
    facility_id: int
    facility_sport_id: int
    sport_id: int
    resource_id: int | None = None
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    effective_from: date | None = None
    effective_until: date | None = None


class ClosureData(BoundaryModel):
    facility_id: int
    resource_id: int | None = None
    start_datetime: datetime
    end_datetime: datetime
    reason: str = ''

    @field_validator('start_datetime', 'end_datetime')
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Datetime values must include a timezone offset.')
        return value


class BookingIntervalData(BoundaryModel):
    resource_id: int
    start_datetime: datetime
    end_datetime: datetime

    @field_validator('start_datetime', 'end_datetime')
    @classmethod
    def require_aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Datetime values must include a timezone offset.')
        return value


class AvailabilityRequest(BoundaryModel):
    target_date: date
    evaluated_at: datetime
    facilities: list[FacilityData] = Field(max_length=50)
    closures: list[ClosureData] = Field(default_factory=list, max_length=1200)
    schedules: list[ScheduleData] = Field(default_factory=list, max_length=1000)
    existing_bookings: list[BookingIntervalData] = Field(
        default_factory=list,
        max_length=1200,
    )

    @field_validator('evaluated_at')
    @classmethod
    def require_aware_evaluation_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('evaluated_at must include a timezone offset.')
        return value

    @model_validator(mode='after')
    def bound_evaluation_work(self):
        evaluation_date = self.evaluated_at.astimezone(APPLICATION_TIMEZONE).date()
        if abs((self.target_date - evaluation_date).days) > 31:
            raise ValueError('target_date must be within 31 days of evaluated_at.')
        if sum(len(facility.resources) for facility in self.facilities) > 50:
            raise ValueError('A request may include at most 50 courts.')
        return self


class AvailableSlot(BoundaryModel):
    facility_id: int
    resource_id: int
    sport_id: int
    start_datetime: datetime
    end_datetime: datetime


class ScheduleSlot(AvailableSlot):
    availability: Literal['available', 'closed', 'booked', 'past']
    reason: str = ''


class AvailabilityResponse(BoundaryModel):
    available_slots: list[AvailableSlot]
    slots: list[ScheduleSlot] = Field(default_factory=list)
    parallel_elapsed_time: float = Field(ge=0)
