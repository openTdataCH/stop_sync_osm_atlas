"""Versioned, language-independent matching result bundles."""

from .bundle import SCHEMA_VERSION, write_bundle
from .validation import InvalidResult, validate_output, validate_bundle

__all__ = ["SCHEMA_VERSION", "write_bundle", "InvalidResult", "validate_output", "validate_bundle"]
