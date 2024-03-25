from concurrent.futures import ThreadPoolExecutor, wait, Future, as_completed
from threading import Lock
import time

class MyTheadingPool():
    def __init__(self, max=5) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max)
        self.futures = []
        self.wroking = True
        self.lock = Lock()
    
    def add_task(self, func, *args, **kwargs) -> Future | None:
        with self.lock:
            if self.wroking:
                future = self.pool.submit(func, *args, **kwargs)
                self.futures.append(future)
                return future
            return None

    def wait(self):
        while self.futures:
            # wait只会等待刚开始传入的，后面变动不会等
            # 加个循环一直等
            wait(self.futures)
            for future in as_completed(self.futures):   
                e = future.exception()
                print(f"Result: {e}")
                self.futures.remove(future)

    def close(self):
        self.stop_working()
        self.pool.shutdown(wait=True)

    def stop_working(self):
        with self.lock:
            self.wroking = False