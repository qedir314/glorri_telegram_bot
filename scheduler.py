"""
Scheduler for Glorri Jobs Bot.
Runs scraping (both glorri.az + jobsearch.az in parallel) and Telegram
notifications every 3 hours.
"""

import sys
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Load environment variables + configure logging (must be first)
import src.config  # noqa: F401

# Import from src packages
from src.scraper import (
    GlorriDriver,
    JobSearchAzDriver,
    run_async_scraper,
    run_jobsearch_async_scraper,
)
from src.database import insert_jobs_bulk, get_job_count
from src.bot import run_send_jobs, run_test_message


logger = logging.getLogger(__name__)


def _scrape_glorri() -> list:
    """Scrape job listings from jobs.glorri.az (for use in thread pool)."""
    logger.info("[Glorri] Starting scraper...")
    with GlorriDriver(headless=True) as driver:
        driver.wait_for_page_load(3)
        jobs = driver.scroll_until_days_old(target_days=7)
        logger.info("[Glorri] Loaded %d job listings", len(jobs))
    return jobs


def _scrape_jobsearch() -> list:
    """Scrape job listings from jobsearch.az (for use in thread pool)."""
    logger.info("[JobSearch.az] Starting scraper...")
    with JobSearchAzDriver(headless=True) as driver:
        driver.wait_for_page_load(3)
        jobs = driver.scroll_until_days_old(target_days=7)
        logger.info("[JobSearch.az] Loaded %d job listings", len(jobs))
    return jobs


def scrape_and_notify():
    """Main job: scrape new jobs from both websites in parallel and send notifications."""
    sep = "=" * 60
    logger.info(sep)
    logger.info("Job started at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(sep)

    try:
        # Step 1: Scrape both websites in parallel
        logger.info("--- Step 1: Scraping jobs from both websites (parallel) ---")
        all_jobs = []
        scraper_errors = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(_scrape_glorri): "Glorri",
                executor.submit(_scrape_jobsearch): "JobSearch.az",
            }

            for future in as_completed(futures):
                scraper_name = futures[future]
                try:
                    jobs = future.result()
                    all_jobs.extend(jobs)
                    logger.info("[%s] Completed: %d jobs", scraper_name, len(jobs))
                except Exception as e:
                    logger.error("[%s] Scraper failed: %s", scraper_name, e, exc_info=True)
                    scraper_errors.append(scraper_name)

        if scraper_errors:
            logger.warning("Some scrapers failed: %s", ", ".join(scraper_errors))

        # Save all jobs to database
        inserted, skipped = insert_jobs_bulk(all_jobs)
        logger.info("Inserted: %d new jobs", inserted)
        logger.info("Skipped: %d existing jobs", skipped)
        logger.info("Total in database: %d", get_job_count())

        # Ensure SQLite has flushed the bulk insert before detail scrapers query
        time.sleep(1)

        # Step 2: Scrape job details for new jobs (both in parallel)
        logger.info("--- Step 2: Fetching job details from both websites ---")
        detail_errors = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            detail_futures = {
                executor.submit(run_async_scraper, 5): "Glorri details",
                executor.submit(run_jobsearch_async_scraper, 10): "JobSearch.az details",
            }

            for future in as_completed(detail_futures):
                name = detail_futures[future]
                try:
                    successful, failed = future.result()
                    logger.info("[%s] Completed: %d successful, %d failed", name, successful, failed)
                except Exception as e:
                    logger.error("[%s] Detail scraper failed: %s", name, e, exc_info=True)
                    detail_errors.append(name)

        if detail_errors:
            logger.warning("Some detail scrapers failed: %s", ", ".join(detail_errors))

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
