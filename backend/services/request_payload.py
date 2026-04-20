"""Helpers for safely reading request payloads across content types."""

from __future__ import annotations

import json


def read_request_payload(request, *, include_query_args: bool = True) -> dict:
    """Read request payload without forcing JSON content type.

    Returns a dictionary parsed from JSON object body, form fields, or
    optionally query args. Non-dict JSON payloads are ignored.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data

    if request.form:
        raw_form = request.form.to_dict(flat=False)
        normalized_form = {}
        for key, values in raw_form.items():
            normalized_key = key[:-2] if key.endswith('[]') else key
            normalized_form[normalized_key] = values[0] if len(values) == 1 else values
        return normalized_form

    raw_body = request.get_data(cache=True, as_text=True)
    if raw_body:
        try:
            parsed = json.loads(raw_body)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    if include_query_args and request.args:
        return request.args.to_dict(flat=True)

    return {}