"""Cache validated upstream snapshots per URL within one Flask process."""
from types import SimpleNamespace

import requests

from ..cache import TTLCache
from .mta_client import ALERTS_URL, fetch_feed


class CachedFeedSession:
    def __init__(self, ttl, max_age, alerts_max_age):
        self.cache = TTLCache()
        self.ttl = ttl
        self.max_age = max_age
        self.alerts_max_age = alerts_max_age

    def get(self, url, *, timeout):
        def load():
            response = requests.get(url, timeout=timeout)
            # Validate before caching. MTAClient also validates on every cache hit,
            # so an aging cached snapshot can never bypass the freshness policy.
            fetch_feed(url, timeout=timeout,
                       max_age=self.alerts_max_age if url == ALERTS_URL else self.max_age,
                       session=SimpleNamespace(get=lambda *args, **kwargs: response))
            return response

        return self.cache.get_or_load(url, self.ttl, load)
