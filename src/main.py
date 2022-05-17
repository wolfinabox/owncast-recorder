import os, sys
import platform
import subprocess
import requests
import argparse
import time
from datetime import datetime
import logging
from owncast import OwncastServer
from processer import ProcesserQueue
from recorder import Recorder
from utils import check_installed, is_docker, configure_logging


def create_argparser() -> argparse.ArgumentParser:
    """Creates the argument parser

    Returns:
        argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        description="Automatic recorder for Owncast streams"
    )
    parser.add_argument(
        "server",
        type=str,
        nargs="?",
        help='Owncast server to record from (eg: "https://oc.mysite.com" or "http://192.168.50.12:8080")',
        default=os.environ.get("SERVER"),
    )
    parser.add_argument(
        "--output",
        "-o",
        help="directory to output recorded files to",
        default=is_docker() and "/data" or os.path.abspath(os.getcwd()),
    )
    parser.add_argument(
        "--interval",
        "-n",
        type=int,
        help="time in seconds between checks to see if stream is live",
        default=os.environ.get("INTERVAL", 1),
    )
    parser.add_argument(
        "--retries",
        "-r",
        type=int,
        help="number of retry attempts when connecting to server. -1 = unlimited",
        default=os.environ.get("RETRIES", 2),
    )
    parser.add_argument(
        "--outformat",
        "-f",
        help="output file/folder name format. supports Python strftime variables and the following: {stream_title}",
        default=os.environ.get("OUTFORMAT", "%m-%d-%y_%H;%M;%S_{stream_title}"),
    )
    parser.add_argument(
        "--segtime",
        "-s",
        type=int,
        help="FFmpeg segment time; length of each recording chunk in seconds",
        default=os.environ.get("SEGTIME", 10),
    )
    parser.add_argument(
        "--deletetsfiles",
        "-d",
        help="automatically delete .ts files once recording is finished processing",
        action="store_true",
        default=os.environ.get("DELETETSFILES", True),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        help="Logging verbosity",
        action="count",
        default=int(os.environ.get("VERBOSITY", 2)),
    )
    return parser


if __name__ == "__main__":
    parser = create_argparser()
    sys.argv.pop(0)  # remove first .py or .exe argument
    args = parser.parse_args(sys.argv)
    # configure logging based on verbosity
    logger = configure_logging(
        "owncastrecorder",
        {
            0: logging.ERROR,
            1: logging.WARNING,
            2: logging.INFO,
            3: logging.DEBUG,
        }.get(args.verbose, 3),
    )

    # at least server argument is required
    if not args.server:
        print(args)
        sys.exit(parser.print_usage())

    logger.debug(f"ARGS: {sys.argv}")
    logger.debug(f'ENV: {",".join(f"{k}:{v}" for k,v in os.environ.items())}')
    logger.debug(
        f"PLATFORM: {platform.system()}" + (" (Docker)" if is_docker() else "")
    )

    # check if ffmpeg is installed
    if check_installed("ffmpeg"):
        logger.debug("Using FFmpeg version:")
        ffmpeg_info = subprocess.run(
            ["ffmpeg", "-version"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).stdout.decode("utf-8")
        logger.debug(ffmpeg_info)
    else:
        logger.error("FFmpeg not found. Please install FFmpeg and add it to PATH.")
        sys.exit(-1)

    # check if we can write to output dir
    # check if output dir exists
    if not os.path.isdir(args.output):
        logger.error(f"Output path {args.output} does not exist")
        sys.exit(-1)
    # try writing to it
    try:
        p = os.path.join(args.output, "test.txt")
        with open(p, "w") as f:
            f.write("Hello world from owncast recorder <3")
        os.remove(p)
    except OSError as e:
        logger.error(e)
        sys.exit(-1)

    # set up Owncast connection
    oc = OwncastServer(args.server, retries=args.retries, logger=logger)
    logger.info(f'Connecting to "{args.server}"')
    try:
        if oc.ping()[1]:
            logger.info(f'Connected to "{args.server}"')
        else:
            logger.error(f'Could not connect to "{args.server}"')
            sys.exit(-1)
    except requests.exceptions.ConnectionError as e:
        logger.error(f'Could not connect to "{args.server}"')
        logger.error(e)
        sys.exit(-1)

    status = oc.status()

    logger.info(f'Server running Owncast v{status[1].get("versionNumber"," UNKNOWN")}')
    logger.info("Waiting for stream...")
    try:
        recorder = Recorder(oc.stream_url(), args.output, args.segtime, logger)
        processer = ProcesserQueue(args.output, args.deletetsfiles, logger)
        processer.process_existing()
        curr_stream_title = None
        connected = True
        while True:
            try:
                code, status = oc.status()
            except requests.exceptions.ConnectionError as e:
                connected = False
                logger.error(f'Lost connection to "{args.server}"')
            # offline
            if not status.get("online", False) or connected == False:
                time.sleep(args.interval)
                if recorder.running:
                    # stream finished
                    recorder.stop()
                    logger.info("Stopped recording (stream/server offline)")
                    # start processing recording
                    processer.add_job(curr_stream_title)

            # online
            else:
                # already recording
                if recorder.running:
                    time.sleep(args.interval)
                # new stream
                else:
                    logger.info(
                        f"Stream \"{status.get('streamTitle','untitled')}\" went live"
                    )
                    # generate title
                    curr_stream_title = args.outformat
                    curr_stream_title = datetime.strftime(
                        datetime.now(), curr_stream_title
                    )
                    curr_stream_title = curr_stream_title.format(
                        stream_title=status.get("streamTitle", "untitled")
                    )
                    logger.info(f'Recording to "{curr_stream_title}"')
                    recorder.start(curr_stream_title)

    except KeyboardInterrupt:
        logger.info("Stopping...")
        recorder.stop()
        processer.stop_all()
