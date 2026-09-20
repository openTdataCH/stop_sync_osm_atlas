"""Optional network acquisition clients.

Acquisition is separate from adapters so local-file matching never implies
network access.
"""

from .overpass import query_overpass

__all__ = ["query_overpass"]
