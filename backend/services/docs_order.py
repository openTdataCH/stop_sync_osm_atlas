"""Reading order of documentation files, shared by the portal and the PDF."""

import os
import re

_NUMBER_PREFIX = re.compile(r'\d+(?:\.\d+)*')


def doc_sort_key(filename: str):
    """Order by section number: '2. Web app', '2.1 …', '2.9 …', '2.10 …'; unnumbered pages last."""
    name = os.path.basename(filename).lower()
    match = _NUMBER_PREFIX.match(name)
    numbers = tuple(int(part) for part in match.group().split('.')) if match else ()
    return (match is None, numbers, name)
