import os

import uvicorn
from fastapi import FastAPI

from .evaluator import run_parallel_evaluation
from .schemas import AvailabilityRequest, AvailabilityResponse

app = FastAPI(
    title='Naval Court Booking Availability Service',
    version='0.1.0',
)


@app.post('/availability/search', response_model=AvailabilityResponse)
def search_availability(request: AvailabilityRequest) -> AvailabilityResponse:
    available_slots, elapsed_time = run_parallel_evaluation(request)
    return AvailabilityResponse(
        available_slots=available_slots,
        parallel_elapsed_time=elapsed_time,
    )


if __name__ == '__main__':
    uvicorn.run(
        app,
        host=os.environ.get('FASTAPI_HOST', '127.0.0.1'),
        port=int(os.environ.get('FASTAPI_PORT', '8001')),
    )
