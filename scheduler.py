"""
Scheduler for Glorri Jobs Bot.
Runs scraping and Telegram notifications every 3 hours.
"""

import sys
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Load environment variables + configure logging (must be first)
import src.config  # noqa: F401

# Import from src packages
from src.scraper import GlorriDriver, run_async_scraper
from src.database import insert_jobs_bulk, get_job_count
from src.bot import run_send_jobs, run_test_message


logger = logging.getLogger(__name__)


def scrape_and_notify():
    """Main job: scrape new jobs and send notifications."""
    sep = "=" * 60
    logger.info(sep)
    logger.info("Job started at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(sep)

    try:
        # Step 1: Scrape new jobs
        logger.info("--- Step 1: Scraping jobs ---")
        with GlorriDriver(headless=True) as driver:
            driver.wait_for_page_load(3)
            jobs = driver.scroll_until_days_old(target_days=7)

            # Save to database
            inserted, skipped = insert_jobs_bulk(jobs)
            logger.info("Inserted: %d new jobs", inserted)
            logger.info("Skipped: %d existing jobs", skipped)
            logger.info("Total in database: %d", get_job_count())

        # Step 2: Scrape job details for new jobs
        logger.info("--- Step 2: Fetching job details ---")
        run_async_scraper(max_concurrent=5)

        # Step 3: Send new jobs to Telegram
        logger.info("--- Step 3: Sending to Telegram ---")
        sent, skipped, failed = run_send_jobs()

        logger.info(sep)
        logger.info("Job completed at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info(sep)

    except Exception as e:
        logger.error("Error during scheduled job: %s", e, exc_info=True)


def run_scheduler(interval_minutes: int = 180):
    """Run the scheduler.

    Args:
        interval_minutes: Interval in minutes (default 180 = 3 hours)
    """
    sep = "=" * 60
    logger.info(sep)
    logger.info("Glorri Jobs Bot Scheduler")
    logger.info(sep)
    logger.info("Started at: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Schedule: Every %d minutes", interval_minutes)
    logger.info(sep)

    # Test Telegram connection first
    logger.info("--- Testing Telegram connection ---")
    if not run_test_message():
        logger.warning("Failed to connect to Telegram. Check your credentials.")
        logger.warning("Continuing anyway...")

    # Run immediately on start
    logger.info("--- Running initial scrape ---")
    scrape_and_notify()

    # Set up scheduler
    scheduler = BlockingScheduler()

    # Schedule job at interval
    scheduler.add_job(
        scrape_and_notify,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="scrape_and_notify",
        name=f"Scrape and notify every {interval_minutes} minutes",
        replace_existing=True,
    )

    logger.info(sep)
    logger.info("Scheduler is running. Press Ctrl+C to stop.")
    logger.info("   Next run in %d minutes", interval_minutes)
    logger.info(sep)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


def run_once():
    """Run scrape and notify once (for testing)."""
    logger.info("=" * 60)
    logger.info("Glorri Jobs Bot - Single Run")
    logger.info("=" * 60)
    scrape_and_notify()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--once":
            # Run once and exit
            run_once()
        elif sys.argv[1] == "--test":
            # Run with 2-minute interval for testing
            run_scheduler(interval_minutes=2)
        else:
            print("Usage: python scheduler.py [--once | --test]")
            print("  --once  : Run once and exit")
            print("  --test  : Run with 2-minute interval for testing")
            print("  (no arg): Run with 3-hour interval")
    else:
        # Run scheduler with 3-hour interval
        run_scheduler(interval_minutes=180)
