from concurrent.futures import ThreadPoolExecutor, wait, ALL_COMPLETED, Future

class MyTheadingPool():
    def __init__(self, max=5) -> None:
        self.pool = ThreadPoolExecutor(max_workers=max)
    
    def add_task(self, func, *args, **kwargs) -> Future:
        return self.pool.submit(func, *args, **kwargs)

    def wait(self, futures: list[Future]):
        wait(futures, return_when=ALL_COMPLETED)
    
    def close(self):
        self.pool.shutdown()