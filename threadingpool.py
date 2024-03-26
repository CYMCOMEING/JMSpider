from concurrent.futures import ThreadPoolExecutor, wait, Future, as_completed
from threading import Lock
import logging


class MyTheadingPool():
    def __init__(self, max=5) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max)
        self.futures:list[Future] = []
        self._wroking = True
        self._lock = Lock()

    def add_task(self, func, *args, **kwargs) -> Future | None:
        with self._lock:
            if self._wroking:
                future = self.pool.submit(func, *args, **kwargs)
                self.futures.append(future)
                return future
            return None

    def wait(self, timeout: float | None = None, logger: logging.Logger | None = None):
        wait(self.futures, timeout=timeout)
        for future in as_completed(self.futures, timeout=1):
            e = future.exception()
            if e and logger:
                logger.error(e)
            self.futures.remove(future)

    def close(self):
        self._stop_working()
        self.pool.shutdown(wait=True)

    def _stop_working(self):
        with self._lock:
            self._wroking = False
        for future in self.futures:
            future.cancel()