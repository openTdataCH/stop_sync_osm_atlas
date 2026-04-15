import re

file_path = "backend/blueprints/docs.py"
with open(file_path, "r") as f:
    content = f.read()

# Make _read_request_payload ultra robust
old_read = """def _read_request_payload() -> dict:
    \"\"\"Read request payload without raising 415 for non-JSON content types.\"\"\"
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    if request.form:
        return request.form.to_dict(flat=True)
    return {}"""

new_read = """def _read_request_payload() -> dict:
    \"\"\"Read request payload without raising 415 for non-JSON content types.\"\"\"
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    # Fallback for form data (including array trickery)
    if request.form:
        d = request.form.to_dict(flat=False)
        flat_d = {}
        for k, v in d.items():
            key = k.replace('[]', '')
            if len(v) == 1:
                flat_d[key] = v[0]
            else:
                            = v
        return flat_d
    # Last resort fallback if data was sent as raw bytes but get_json failed
    try:
        import json
        return json.loads(request.get_data(as_text=True))
    except Exception:
        pass
    return {}"""

content = content.replace(old_read, new_read)

with open(file_path, "w") as f:
    f.write(content)
