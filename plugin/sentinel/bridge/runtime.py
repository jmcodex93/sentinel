"""Thread hand-off queue and background-job state for Sentinel's bridge."""

import itertools
import queue
import threading
import time
import traceback

from sentinel.common.logging import exception as log_exception
from sentinel.common.logging import info as log_info


class _QueuedRequest:
    __slots__ = ("payload", "event", "result", "cancelled", "lock")

    def __init__(self, payload):
        self.payload = payload
        self.event = threading.Event()
        self.result = None
        self.cancelled = False
        self.lock = threading.Lock()


class MainThreadQueue:
    """Cross-thread hand-off drained from Cinema 4D's main-thread timer."""

    MAX_ITEMS_PER_TICK = 8
    MAX_SECONDS_PER_TICK = 0.1

    def __init__(self):
        self._queue = queue.Queue()
        self.last_drain_backlog = 0
        self.backlog_high = 0

    def submit(self, payload, timeout=30.0):
        """Wait for main-thread dispatch, cancelling atomically on timeout."""
        request = _QueuedRequest(payload)
        self._queue.put(request)
        if request.event.wait(timeout):
            return request.result

        with request.lock:
            if request.event.is_set():
                return request.result
            request.cancelled = True
        raise TimeoutError("keep the Reports window open")

    def drain(self, dispatch, max_items=None, max_seconds=None):
        """Dispatch a bounded queue slice; this method never raises."""
        if max_items is None:
            max_items = self.MAX_ITEMS_PER_TICK
        if max_seconds is None:
            max_seconds = self.MAX_SECONDS_PER_TICK
        deadline = time.monotonic() + max_seconds
        items_this_tick = 0

        while True:
            try:
                request = self._queue.get_nowait()
            except queue.Empty:
                self.last_drain_backlog = 0
                return

            with request.lock:
                if request.cancelled:
                    continue

                try:
                    request.result = dispatch(request.payload)
                except Exception as exc:
                    op = None
                    if isinstance(request.payload, dict):
                        op = request.payload.get("op")
                    log_exception(
                        "queue.dispatch_failed",
                        "webbridge.runtime",
                        exc,
                        op=op,
                    )
                    request.result = {
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                finally:
                    request.event.set()

            items_this_tick += 1
            if items_this_tick >= max_items or time.monotonic() >= deadline:
                remaining = self._queue.qsize()
                self.last_drain_backlog = remaining
                if remaining:
                    self.backlog_high += 1
                return


class JobRegistry:
    """Thread-safe, single-slot registry for background Hub jobs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = itertools.count(1)
        self._job = None

    def start(self, spec):
        with self._lock:
            if self._job is not None and self._job["state"] in (
                "pending", "running"
            ):
                raise RuntimeError("job_running")
            job_id = "job-%d" % next(self._counter)
            self._job = {
                "job_id": job_id,
                "spec": spec,
                "state": "pending",
                "phase": "",
                "detail": "",
                "pct": 0,
                "result": None,
                "error": None,
            }
            return job_id

    def take_pending(self):
        with self._lock:
            job = self._job
            if job is None or job["state"] != "pending":
                return None
            job["state"] = "running"
            return job["job_id"], job["spec"]

    def _if_current(self, job_id):
        job = self._job
        return job if (
            job is not None and job["job_id"] == job_id
        ) else None

    def update(self, job_id, phase, detail="", pct=None):
        with self._lock:
            job = self._if_current(job_id)
            if job is None:
                return
            job["phase"] = phase
            job["detail"] = detail
            if pct is not None:
                job["pct"] = pct

    def finish(self, job_id, result):
        with self._lock:
            job = self._if_current(job_id)
            if job is not None:
                job["state"] = "done"
                job["result"] = result
                job["pct"] = 100

    def fail(self, job_id, error):
        with self._lock:
            job = self._if_current(job_id)
            if job is not None:
                job["state"] = "error"
                job["error"] = str(error)
                log_info(
                    "job.failed",
                    "webbridge.runtime",
                    job_id=job_id,
                    error=job["error"],
                )

    def status(self, job_id):
        with self._lock:
            job = self._if_current(job_id)
            if job is None:
                return {"error": "unknown_job"}
            snap = dict(job)
            snap.pop("spec", None)
            return snap
