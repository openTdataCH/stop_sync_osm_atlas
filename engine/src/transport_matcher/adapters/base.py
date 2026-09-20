"""Source-adapter contract shared by built-in and external integrations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from transport_matcher.core.state import SourceState


@dataclass
class AdapterResult:
    """Normalized input plus optional route products, extensions and provenance.

    Adapter implementations own source syntax. Matching policy remains in a
    profile, and presentation remains in a result consumer.
    """

    source: SourceState
    route_data: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    """Structural interface for an adapter callable.

    External adapters do not need to be registered in this distribution. They
    can return ``AdapterResult`` and pass its normalized state to the public API.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> AdapterResult: ...
