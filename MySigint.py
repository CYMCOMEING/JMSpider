import signal

class MySigint():
    """捕获中断信号(Ctrl+C)，进行对应处理
    """
    def __init__(self) -> None:
        self._result = None
        self._init()

    def listening(self, func, /, *args, **kwargs) -> bool:
        if self._is_listening:
            return False
        else:
            self._is_listening = True
            self._func = func
            self._args = args
            self._kwargs = kwargs
            self._old_handler = signal.signal(signal.SIGINT, self._handler)
            return True
    
    def _handler(self, signum, frame):
        self._result = self._func(*self._args, **self._kwargs)

    def result(self):
        ret = self._result
        self._result = None
        return ret
    
    def stop(self):
        if self._is_listening:
            signal.signal(signal.SIGINT, self._old_handler)
            self._init()

    def _init(self):
        self._func = None
        self._args = None
        self._kwargs = None
        self._old_handler = None
        self._is_listening = False