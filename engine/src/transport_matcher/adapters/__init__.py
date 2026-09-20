"""Curated format readers outside the matching core.

External adapters can implement :class:`SourceAdapter` without being registered
in this package. Import individual built-ins to keep dependencies lazy.
"""

from .base import AdapterResult, SourceAdapter

__all__ = ["AdapterResult", "SourceAdapter"]
