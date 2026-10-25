from threading import RLock
from time import monotonic

class TTLCache:
    """Process-local cache; use shared storage before deploying multiple workers."""
    def __init__(self):
        self._values = {}
        self._lock = RLock()

    def get_or_load(self, key, ttl, loader):
        with self._lock:
            value = self._values.get(key)
            if value and value[0] > monotonic():
                return value[1]
            result = loader()
            self._values[key] = (monotonic() + ttl, result)
            return result
