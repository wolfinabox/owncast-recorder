from queue import Empty
import shutil
import platform
from threading import Event, Thread
from multiprocessing import Queue
import logging
from typing import IO
import os


def configure_logging(name: str, level: int) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    formatter = logging.Formatter("%(asctime)s:[%(levelname)s][%(name)s] - %(message)s")
    ch = logging.StreamHandler()
    ch.setLevel(level=level)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger


def check_installed(program: str) -> bool:
    """Checks if the given program is installed using `which`

    Args:
        program (str):Program to check for

    Returns:
        bool: True/False if program is installed or not
    """
    return shutil.which(program) is not None


def is_docker():
    """Returns True if running in a Docker container, False otherwise

    Returns:
        _type_: _description_
    """
    # Modified from  https://stackoverflow.com/a/48710609
    if platform.system() != "Linux":
        return False
    path = "/proc/self/cgroup"
    return (
        os.path.exists("/.dockerenv")
        or os.path.isfile(path)
        and any("docker" in line for line in open(path))
    )


class NonBlockingStreamReader:
    def __init__(self, stream: IO, default=None, readline=True, read_amt=-1):
        self.stream = stream
        self.default = default
        self.readline = readline
        self.read_amt = read_amt
        self.data: Queue = Queue()
        self._running = Event()
        self.stream_thread: Thread = Thread(
            target=self._run_loop, name=f"noblockingstreamreader-thread-{id(self)}"
        )
        self._running.set()
        self.stream_thread.start()

    def __iter__(self):
        return self

    def __next__(self):
        return self.next()

    def _run_loop(self):
        while self._running.is_set():
            try:
                if self.readline:
                    data = self.stream.readline()
                else:
                    data = self.stream.read(-1)
                if not data:
                    self._running.clear()
                else:
                    self.data.put_nowait(data)
            except EOFError:
                self._running.clear()

    def close(self):
        return self.stream.close()

    def next(self):
        # end of stream
        if not self._running.is_set():
            raise StopIteration
        try:
            return self.data.get_nowait()
        except Empty:
            return self.default
