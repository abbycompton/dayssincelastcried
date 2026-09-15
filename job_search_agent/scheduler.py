"""Daily scheduler using APScheduler, as an alternative to a system cron job.

Usage:
    python -m job_search_agent.scheduler          # runs daily at 07:00 local time
    python -m job_search_agent.scheduler --at 06:30
    python -m job_search_agent.scheduler --now     # run once immediately, then exit

If you'd rather use a real cron job instead of keeping this process running,
add a line like:
    0 7 * * * cd /path/to/repo && /path/to/venv/bin/python -m job_search_agent.main >> logs/cron.log 2>&1
"""

from __future__ import annotations

import argparse
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from .main import run

logger = logging.getLogger("job_search_agent")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--at", default="07:00", help="Local time (HH:MM) to run daily. Default 07:00.")
    parser.add_argument("--now", action="store_true", help="Run once immediately and exit, skipping the schedule.")
    args = parser.parse_args()

    if args.now:
        run()
        return

    hour, minute = (int(part) for part in args.at.split(":"))
    scheduler = BlockingScheduler()
    scheduler.add_job(run, "cron", hour=hour, minute=minute, id="daily_job_search_digest")
    logger.info("Scheduled daily run at %02d:%02d local time. Press Ctrl+C to stop.", hour, minute)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
