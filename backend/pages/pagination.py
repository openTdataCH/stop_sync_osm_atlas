"""Paging for the list pages (routes, operators): the page parameters and the "Showing a-b of n" range."""


def bounded_int(value, default, minimum, maximum=None):
    """``value`` as a whole number within ``minimum``..``maximum``; ``default`` when it is not a number."""
    try:
        value = max(int(value), minimum)
    except (TypeError, ValueError):
        return default
    return value if maximum is None else min(value, maximum)


def per_page_choice(value, options, default, minimum):
    """The number of entries per page: ``value`` within ``minimum``..the largest option, ``default`` when no option."""
    chosen = bounded_int(value, default, minimum, max(options))
    return chosen if chosen in options else default


def page_range(pagination):
    """The numbers of the first and last entries of the page, (0, 0) when the page is empty."""
    start = (pagination.page - 1) * pagination.per_page + 1
    if start > pagination.total:
        return 0, 0
    return start, min(start + pagination.per_page - 1, pagination.total)


class ListPagination:
    """One page of an already counted list, with the attributes the pagination templates read."""

    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = ((total - 1) // per_page) + 1 if total > 0 else 0
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = max(page - 1, 1)
        self.next_num = min(page + 1, self.pages or 1)

    def iter_pages(self, left_edge=1, left_current=1, right_current=2, right_edge=1):
        pages = []
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    pages.append(None)
                pages.append(num)
                last = num
        return pages
