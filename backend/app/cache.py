from threading import Lock, RLock
from time import monotonic


class TTLCache:
    """Process-local cache; use shared storage before deploying multiple workers.

    Loads run under a per-key lock, so concurrent callers of one key share a single
    upstream fetch while other keys are not blocked by a slow upstream. A loader
    exception is never cached. Expired entries are pruned as new values are stored.
    """
    def __init__(self):
        self._values = {}
        self._lock = RLock()
        self._key_locks = {}

    def _key_lock(self, key):
        with self._lock:
            return self._key_locks.setdefault(key, Lock())

    def _fresh(self, key):
        with self._lock:
            value = self._values.get(key)
            return value if value and value[0] > monotonic() else None

    def get_or_load(self, key, ttl, loader):
        value = self._fresh(key)
        if value:
            return value[1]
        with self._key_lock(key):
            value = self._fresh(key)  # Another caller may have loaded it while we waited.
            if value:
                return value[1]
            result = loader()
            now = monotonic()
            with self._lock:
                for stale in [k for k, (expires, _) in self._values.items() if expires <= now]:
                    del self._values[stale]
                    if stale != key:
                        self._key_locks.pop(stale, None)
                self._values[key] = (now + ttl, result)
            return result

    def evict(self, key):
        with self._lock:
            self._values.pop(key, None)
