import hashlib
import ipaddress
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse


RATE_LIMITS = (
    ('registration', {
        'paths': {'/register/', '/signup/', '/accounts/register/'},
        'methods': {'POST'},
        'limit': 5,
        'window': 60,
        'identity': 'ip',
    }),
    ('login', {
        'paths': {'/', '/login/', '/accounts/login/'},
        'methods': {'POST'},
        'limit': 8,
        'window': 60,
        'identity': 'login',
    }),
    ('owner-management', {
        'prefixes': ('/owner/dashboard/', '/management/'),
        'methods': {'POST'},
        'limit': 10,
        'window': 60,
        'identity': 'user',
    }),
    ('booking', {
        'paths': {'/api/bookings/'},
        'methods': {'POST'},
        'limit': 15,
        'window': 60,
        'identity': 'user_ip',
    }),
    ('availability', {
        'availability': True,
        'methods': {'GET'},
        'limit': 60,
        'window': 60,
        'identity': 'user_ip',
    }),
)


def _client_ip(request, proxy_allowlist):
    remote_addr = request.META.get('REMOTE_ADDR', '')
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return 'unknown'

    trusted_proxies = []
    for value in proxy_allowlist:
        try:
            trusted_proxies.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    def is_trusted_proxy(address):
        return any(
            address.version == network.version and address in network
            for network in trusted_proxies
        )

    if not is_trusted_proxy(remote_ip):
        return str(remote_ip)

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    chain = []
    for value in forwarded.split(','):
        try:
            chain.append(ipaddress.ip_address(value.strip()))
        except ValueError:
            return str(remote_ip)
    chain.append(remote_ip)
    while len(chain) > 1 and is_trusted_proxy(chain[-1]):
        chain.pop()
    return str(chain[-1])


def _matches(rule, request):
    if request.method not in rule['methods']:
        return False
    path = request.path
    if 'paths' in rule and path not in rule['paths']:
        return False
    if 'prefixes' in rule and not any(
        path.startswith(prefix) for prefix in rule['prefixes']
    ):
        return False
    if rule.get('availability') and not (
        path.rstrip('/').endswith('/availability/search')
        or path.rstrip('/').endswith('/availability')
    ):
        return False
    return True


def _identity(rule, request, client_ip):
    strategy = rule['identity']
    if strategy == 'ip':
        return client_ip
    if strategy == 'login':
        username = request.POST.get('username', '').strip().casefold()[:150]
        return f'{client_ip}:{username}'
    if strategy == 'user':
        return f'user:{request.user.pk}' if request.user.is_authenticated else client_ip
    user_id = f'user:{request.user.pk}' if request.user.is_authenticated else 'anonymous'
    return f'{user_id}:{client_ip}'


def _increment_fixed_window(key, timeout):
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        if cache.add(key, 1, timeout=timeout):
            return 1
        return cache.incr(key)


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        client_ip = _client_ip(request, settings.TRUSTED_PROXY_IPS)
        now = int(time.time())

        for name, rule in RATE_LIMITS:
            if not _matches(rule, request):
                continue
            window_id = now // rule['window']
            identity = _identity(rule, request, client_ip)
            digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()
            key = f'rate-limit:{name}:{digest}:{window_id}'
            count = _increment_fixed_window(key, rule['window'] * 2)
            if count > rule['limit']:
                retry_after = rule['window'] - (now % rule['window'])
                if request.path.startswith('/api/'):
                    response = JsonResponse(
                        {'detail': 'Too many requests. Please try again shortly.'},
                        status=429,
                    )
                else:
                    response = HttpResponse(
                        '<!doctype html><title>Too many requests</title>'
                        '<p>Too many requests. Please wait a moment and try again.</p>',
                        status=429,
                    )
                response['Retry-After'] = str(retry_after)
                return response
        return self.get_response(request)
