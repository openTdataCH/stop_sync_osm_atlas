"""Structured wall/CPU timings with a heartbeat for long-running stages."""
from contextlib import contextmanager
import json
import threading
import time


@contextmanager
def stage(name, **details):
    started, cpu = time.perf_counter(), time.process_time()
    done = threading.Event()

    def emit(event, **extra):
        print(json.dumps({"event": event, "stage": name,
                          "seconds": round(time.perf_counter() - started, 3),
                          **details, **extra}), flush=True)

    def heartbeat():
        while not done.wait(30):
            emit("stage_progress")

    emit("stage_started")
    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    error = None
    try:
        yield
    except BaseException as exc:
        error = exc
        raise
    finally:
        # Stop the heartbeat first, so no progress line follows the final one.
        done.set()
        worker.join()
        cpu_seconds = round(time.process_time() - cpu, 3)
        if error is None:
            emit("stage_finished", cpu_seconds=cpu_seconds)
        else:
            emit("stage_failed", cpu_seconds=cpu_seconds, error=str(error))
