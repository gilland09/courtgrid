import json
import os
import secrets

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status

from .evaluator import run_parallel_evaluation_with_schedule
from .schemas import AvailabilityRequest, AvailabilityResponse

app = FastAPI(
    title='Naval Court Booking Availability Service',
    version='0.1.0',
)

MAX_REQUEST_BODY_BYTES = 5 * 1024 * 1024


def authorize_compute_node(
    x_compute_service_token: str | None = Header(default=None),
) -> None:
    expected_token = os.environ.get('COMPUTE_SERVICE_TOKEN', '')
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Compute service authentication is not configured.',
        )
    if (
        x_compute_service_token is None
        or not secrets.compare_digest(x_compute_service_token, expected_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Invalid compute service credentials.',
        )


class ComputeRequestGuard:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if (
            scope['type'] != 'http'
            or scope.get('method') != 'POST'
            or scope.get('path') != '/availability/search'
        ):
            await self.application(scope, receive, send)
            return

        headers = dict(scope.get('headers', ()))
        supplied_token = headers.get(b'x-compute-service-token', b'').decode(
            'latin-1',
        )
        expected_token = os.environ.get('COMPUTE_SERVICE_TOKEN', '')
        if not expected_token:
            await self._reject(send, 503, 'Compute service authentication is not configured.')
            return
        if not secrets.compare_digest(supplied_token, expected_token):
            await self._reject(send, 401, 'Invalid compute service credentials.')
            return

        content_length = headers.get(b'content-length')
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_BYTES:
                    await self._reject(send, 413, 'Request body exceeds the allowed size.')
                    return
            except ValueError:
                await self._reject(send, 400, 'Invalid Content-Length header.')
                return

        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > MAX_REQUEST_BODY_BYTES:
                await self._reject(send, 413, 'Request body exceeds the allowed size.')
                return
            body.extend(chunk)
            if not message.get('more_body', False):
                break

        body_bytes = bytes(body)
        replayed = False

        async def replay_body():
            nonlocal replayed
            if replayed:
                return {'type': 'http.disconnect'}
            replayed = True
            return {
                'type': 'http.request',
                'body': body_bytes,
                'more_body': False,
            }

        await self.application(scope, replay_body, send)

    @staticmethod
    async def _reject(send, status_code, message):
        body = json.dumps({'detail': message}).encode('utf-8')
        await send({
            'type': 'http.response.start',
            'status': status_code,
            'headers': [
                (b'content-type', b'application/json'),
                (b'content-length', str(len(body)).encode('ascii')),
            ],
        })
        await send({'type': 'http.response.body', 'body': body})


app.add_middleware(ComputeRequestGuard)


@app.post('/availability/search', response_model=AvailabilityResponse)
def search_availability(
    request: AvailabilityRequest,
    _authorized: None = Depends(authorize_compute_node),
) -> AvailabilityResponse:
    available_slots, slots, elapsed_time = run_parallel_evaluation_with_schedule(request)
    return AvailabilityResponse(
        available_slots=available_slots,
        slots=slots,
        parallel_elapsed_time=elapsed_time,
    )


if __name__ == '__main__':
    uvicorn.run(
        app,
        host=os.environ.get('FASTAPI_HOST', '127.0.0.1'),
        port=int(os.environ.get('FASTAPI_PORT', '8001')),
    )
