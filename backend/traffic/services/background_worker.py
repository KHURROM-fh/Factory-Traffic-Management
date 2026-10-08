"""
Background Timing Worker for Factory Traffic Management System.

Runs a non-blocking daemon thread ticking the SignalTimingService periodically.
Guarantees:
- API requests are NEVER blocked by timing loops.
- Ticks run asynchronously in the background.
- Row-level database locks ensure multi-worker / multi-thread safety.
"""

import logging
import threading
import time
from typing import Optional

from django.db import connections
from traffic.services.timing_service import SignalTimingService

logger = logging.getLogger(__name__)


class BackgroundTimingWorker:
    """
    Lightweight, thread-safe background scheduler worker.
    Periodically triggers SignalTimingService.tick_all_junctions().
    """

    def __init__(self, interval_sec: float = 1.0):
        self.interval_sec = interval_sec
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Starts the background worker thread if not already running."""
        if self.is_running():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="TrafficTimingWorkerThread",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"BackgroundTimingWorker started (interval: {self.interval_sec}s).")

    def stop(self, timeout: float = 2.0) -> None:
        """Signals the background worker thread to stop and waits for termination."""
        if not self.is_running():
            return

        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None
        connections.close_all()
        logger.info("BackgroundTimingWorker stopped.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        """Worker loop executing every interval_sec until stopped."""
        while not self._stop_event.is_set():
            try:
                SignalTimingService.tick_all_junctions()
            except Exception as e:
                logger.error(f"Error in BackgroundTimingWorker loop: {e}", exc_info=True)
            finally:
                connections.close_all()

            # Wait for interval or stop signal
            self._stop_event.wait(timeout=self.interval_sec)


# Global worker instance
timing_worker = BackgroundTimingWorker(interval_sec=1.0)
