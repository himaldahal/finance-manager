"""Small cache-based throttle used for login and registration.

The default cache is per-process memory. Behind several workers, configure a
shared cache backend so counters are shared.
"""
from django.core.cache import cache


def client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")


class Throttle:
    def __init__(self, scope, limit, window):
        self.scope = scope
        self.limit = limit
        self.window = window

    def _key(self, *parts):
        clean = ":".join(str(p).lower().replace(" ", "_")[:80] for p in parts)
        return f"throttle:{self.scope}:{clean}"

    def count(self, *parts):
        return cache.get(self._key(*parts), 0)

    def blocked(self, *parts):
        return self.count(*parts) >= self.limit

    def hit(self, *parts):
        key = self._key(*parts)
        if cache.add(key, 1, self.window):
            return 1
        try:
            return cache.incr(key)
        except ValueError:  # expired between add and incr
            cache.set(key, 1, self.window)
            return 1

    def reset(self, *parts):
        cache.delete(self._key(*parts))
