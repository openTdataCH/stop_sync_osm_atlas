import os
def get_css_content(*paths):
    content = ""
    for path in paths:
        try:
            with open(path, 'r') as f:
                content += f.read() + "\n"
        except Exception:
            pass
    return content
