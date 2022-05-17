# record example: ffmpeg -i https://watch.wolfinabox.com/hls/stream.m3u8 -c copy -map 0 -segment_time 10 -f segment out%03d.ts
import os
import shlex
from threading import Thread, Event
import subprocess
import logging

from utils import NonBlockingStreamReader


class Recorder:
    def __init__(
        self, stream_url: str, output_path: str, segtime: int = 10, logger=None
    ):
        self.stream_url = stream_url
        self.output_path = output_path
        self.segtime = segtime
        self.logger = logger
        if self.logger is None:
            self.logger = logging.getLogger()
        self._running = Event()
        self._thread: Thread = None

    @property
    def running(self):
        return self._running.is_set()

    def start(self, file_name: str):
        if not self._running.is_set():
            self._running.set()
            self._thread = Thread(
                target=self._run_loop, args=(file_name,), name="recorder-thread"
            )
            self._thread.start()

    def stop(self):
        if self._thread and self._running.is_set():
            self._running.clear()
            self._thread.join()
            self._thread = None

    def _run_loop(self, file_name: str):
        path = os.path.join(self.output_path, file_name)
        if not os.path.exists(path):
            os.mkdir(path)
        ffmpeg_command = f'ffmpeg -i "{self.stream_url}" -hide_banner -loglevel error -c copy -segment_time {self.segtime} -f segment "{os.path.join(path,"%05d.ts")}"'
        self.logger.debug(f'Running "{ffmpeg_command}"')
        proc = subprocess.Popen(
            shlex.split(ffmpeg_command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        reader = NonBlockingStreamReader(proc.stdout)
        while True:
            # stopped from above
            if not self._running.is_set():
                proc.kill()
                proc.wait()
                break

            try:
                line = next(reader)
            except StopIteration:
                self._running.clear()
                break
            if not line:
                continue
            line = line.decode("utf-8")
            if not line.strip():
                continue
            if (
                "non-existing SPS 0 referenced in buffering period" in line
                or "Last message repeated" in line
            ):
                continue
            self.logger.debug(line)
