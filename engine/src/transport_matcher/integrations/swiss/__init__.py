"""First-party Swiss ATLAS/GTFS integration.

The imports are intentionally lazy so the base matching package does not need
the optional Swiss processing dependencies.
"""
from __future__ import annotations


def run_matching(*args, **kwargs):
    from transport_matcher.swiss import run_matching as _run_matching
    return _run_matching(*args, **kwargs)


def refresh_swiss(*args, **kwargs):
    from transport_matcher.adapters.acquisition import refresh_swiss as _refresh_swiss
    return _refresh_swiss(*args, **kwargs)


__all__ = ["refresh_swiss", "run_matching"]
