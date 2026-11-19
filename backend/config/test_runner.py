from unittest import TestCase

from django.core.cache import cache
from django.test.runner import DiscoverRunner


class CacheIsolatingDiscoverRunner(DiscoverRunner):
    def build_suite(self, *args, **kwargs):
        suite = super().build_suite(*args, **kwargs)
        for test in self._tests(suite):
            original_set_up = test.setUp

            def set_up_with_cache_clear(original=original_set_up):
                cache.clear()
                original()

            test.setUp = set_up_with_cache_clear
        return suite

    @classmethod
    def _tests(cls, suite):
        for test in suite:
            if isinstance(test, TestCase):
                yield test
            else:
                yield from cls._tests(test)
