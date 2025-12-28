import time
from contextlib import contextmanager
from typing import Iterator, Optional


@contextmanager
def timed_phase(name: str, *, enabled: bool = True) -> Iterator[None]:
    """Lightweight phase timing helper.

    Prints one start and one end line per phase (not overly verbose).
    """
    if not enabled:
        yield
        return

    start = time.time()
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] START {name}")
    try:
        yield
    finally:
        duration = time.time() - start
        ts_end = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts_end}] END   {name} ({duration:.1f}s)")


def format_progress(done: int, total: int, *, start_time: Optional[float] = None) -> str:
    if total <= 0:
        return f"{done}"
    pct = (done / total) * 100.0
    if not start_time:
        return f"{done:,}/{total:,} ({pct:.1f}%)"
    elapsed = max(0.001, time.time() - start_time)
    rate = done / elapsed
    eta_s = int((total - done) / max(rate, 1e-9))
    return f"{done:,}/{total:,} ({pct:.1f}%) | {rate:.1f}/s | ETA {eta_s}s"
