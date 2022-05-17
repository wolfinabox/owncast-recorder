import logging
from queue import Queue
import os
from queue import Empty
import shutil
from threading import Thread, Event
import subprocess
import shlex

from utils import NonBlockingStreamReader


def make_files_list(input_dir: str, file_list_path: str):
    with open(file_list_path, "w") as f:
        for file in os.listdir(input_dir):
            if not file.endswith(".ts"):
                continue
            # check for 0 size files, corrupt
            if os.path.getsize(os.path.join(input_dir, file)) <= 0:
                print(f'Found 0-size (corrupted) file "{file}", ignoring...')
                continue
            f.write(
                f"file '{os.path.join(os.path.abspath(input_dir),file)}'\n".replace(
                    "\\", "/"
                )
            )  # replace \ with / for ffmpeg files list
    return file_list_path


class Processer:
    def __init__(self, output_path: str, file_name: str, logger=None):
        self.output_path = output_path
        self.file_name = file_name
        self.logger = logger
        if self.logger is None:
            self.logger = logging.getLogger()
        self._running = Event()
        self._thread: Thread = None

    @property
    def running(self):
        return self._running.is_set()

    def start(self):
        if not self._running.is_set():
            self._running.set()
            self._thread = Thread(
                target=self._run_loop, name=f"Processer-thread-{self.file_name}"
            )
            self._thread.start()

    def stop(self):
        if self._thread and self._running.is_set():
            self._running.clear()
            self._thread.join()
            self._thread = None

    def _run_loop(self):
        path = os.path.join(self.output_path, self.file_name)
        out_file = os.path.join(self.output_path, self.file_name + ".mkv")
        # create files list
        files_list = make_files_list(path, os.path.join(path, "files.txt"))
        ffmpeg_command = f'ffmpeg -y -f concat -safe 0 -i "{files_list}" -hide_banner -loglevel error -c copy "{out_file}"'
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
            # ignore lines that'll always be there
            if (
                "non-existing SPS 0 referenced in buffering period" in line
                or "Last message repeated" in line
            ):
                continue
            self.logger.debug(line)


class ProcesserQueue:
    def __init__(self, output_path: str, delete_ts_files: bool = True, logger=None):
        self.output_path = output_path
        self.delete_ts_files = delete_ts_files
        self.logger = logger
        if self.logger is None:
            self.logger = logging.getLogger()
        self.processes = Queue()
        self._running = Event()
        self._running.set()
        self._thread: Thread = Thread(
            target=self._run_loop, name="processer-queue-thread"
        )
        self._thread.start()

    @property
    def running(self):
        return self._running.is_set()

    def _run_loop(self):
        while self._running.is_set():
            try:
                job = self.processes.get(True, 1)
            except Empty:
                continue
            else:
                # job still running
                if job[0].running:
                    self.processes.put_nowait(job)
                # job finished
                else:
                    self.logger.info(f'Finished processing "{job[1]}"')
                    shutil.rmtree(os.path.join(self.output_path, job[1]))

    def stop_all(self):
        while True:
            try:
                job = self.processes.get_nowait()
                job[0].stop()
            except Empty:
                self._running.clear()
                self._thread.join()
                return

    def add_job(self, file_name: str):
        self.logger.info(f'Processing "{file_name}"')
        job = Processer(self.output_path, file_name, self.logger)
        job.start()
        self.processes.put_nowait((job, file_name))

    def process_existing(self):
        names = os.listdir(self.output_path)
        need_to_process = []
        for name in names:
            full_path = os.path.join(self.output_path, name)
            # directory
            if os.path.isdir(full_path):
                # check to see if file already processed
                file_would_be = full_path + ".mkv"
                # not already processed
                if not os.path.isfile(file_would_be):
                    need_to_process.append(name)

        if need_to_process:
            self.logger.info(f"Processing {len(need_to_process)} existing recordings")
            for name in need_to_process:
                self.add_job(name)
