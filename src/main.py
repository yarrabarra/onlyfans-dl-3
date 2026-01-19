import click

import os
import sys
import time

from pathlib import Path
from loguru import logger as log
from ofdownloader import OFDownloader


# The default logging level is INFO so we will override to make it DEBUG
def setup_logger(loglevel="INFO"):
    log_path = Path(os.path.join(os.getcwd(), "logs"))
    log_path.mkdir(exist_ok=True)
    log_name = "of.log"
    log_location = log_path / log_name
    log.remove()  # Remove default logger
    log.add(sys.stdout, level=loglevel)
    log.info(f"Starting logs at {log_location}")
    log.add(log_location, level=loglevel)


@click.command()
@click.option(
    "--targets",
    default="all",
    type=click.Choice(["all", "purchased", "messages", "posts"]),
    help="Which items to query",
)
@click.option("--label-id", default=None, help="A specific label id to query, must be used with --subscriptions")
@click.option("--filter", default=None, help="A text filter that will only download posts that match")
@click.option("--subscriptions", default="all", help="Which subscription usernames to query")
@click.option("--loglevel", default="INFO", help="Log level for logging")
@click.option("--max-post-days", default=3, help="Maximum number of days to go back for posts")
@click.option("--session-vars-path", default="session_vars.json", help="Path to the set of session vars to use")
@click.option(
    "--albums",
    default=False,
    type=bool,
    help="Separate photos into subdirectories by post/album (Single photo posts are not put into subdirectories)",
)
@click.option(
    "--use-subfolders",
    default=True,
    type=bool,
    help="Use content type subfolders (messages/archived/stories/purchased),"
    "or download everything to /profile/photos and /profile/videos",
)
def main(targets, subscriptions, loglevel, *_, **__):
    # Session Variables (update every time you login or your browser updates)
    setup_logger(loglevel)

    log.info("Beginning processing...")
    start_time = time.time()
    ofd = OFDownloader()

    success = ofd.run(targets, subscriptions)

    log.info("Processing finished.")
    runtime = time.time() - start_time
    log.info("Run time: {rt} minutes ({secs} seconds)".format(rt=round((runtime / 60), 3), secs=round(runtime, 3)))
    for name, downloads in ofd.new_files.items():
        if len(downloads) == 0:
            continue
        log.info(f"New files for {name}:")
        for download in downloads:
            download = download.replace("\\", "/")
            log.info(f"  {download}")

    log.info("-" * 80)
    return success


if __name__ == "__main__":
    result = main()
    if not result:
        sys.exit(1)
