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
    try:
        yield
    except BaseException:
        emit("stage_failed", cpu_seconds=round(time.process_time() - cpu, 3))
        raise
    else:
        emit("stage_finished", cpu_seconds=round(time.process_time() - cpu, 3))
    finally:
        done.set()
        worker.join()
