"""
Main script for Glorri Jobs Scraper
Uses GlorriDriver to scrape job listings from https://jobs.glorri.az/
Saves jobs to SQLite database and fetches detailed job information
"""

import logging
import src.config  # noqa: F401  -- load .env + configure logging (must be first)

from src.scraper import GlorriDriver, run_async_scraper
from src.database import insert_jobs_bulk, get_job_count, get_job_details_count

logger = logging.getLogger(__name__)


def main():
    """Main function to scrape Glorri jobs and save to database."""
    sep = "=" * 50
    logger.info(sep)
    logger.info("Glorri Jobs Scraper")
    logger.info("Scrolling until last vacancy is 7 days old")
    logger.info(sep)

    # Create driver and run scraper
    with GlorriDriver(headless=False) as driver:
        # Wait for initial page load
        driver.wait_for_page_load(3)

        # Scroll until last vacancy is 7 days old
        logger.info("--- Scrolling to load jobs (until 7 days old) ---")
        jobs = driver.scroll_until_days_old(target_days=7)

        # Summary
        logger.info("--- Loaded %d Job Listings ---", len(jobs))

        # Save jobs to database
        logger.info("--- Saving jobs to database ---")
        inserted, skipped = insert_jobs_bulk(jobs)
        logger.info("Inserted: %d new jobs", inserted)
        logger.info("Skipped: %d existing jobs", skipped)
        logger.info("Total jobs in database: %d", get_job_count())

        # Sample first 3 jobs
        for i, job in enumerate(jobs[:3], 1):
            logger.info("[%d] %s", i, job.title)
            logger.info("    Company: %s", job.company)
            logger.info("    Location: %s", job.location)
            if job.posted_date:
                days_ago = driver.get_days_ago(job.posted_date)
                logger.info(
                    "    Posted: %s (%d days ago)",
                    job.posted_date.strftime("%d-%m-%Y"),
                    days_ago,
                )
            if job.job_url:
                logger.info("    URL: %s", job.job_url)

        if len(jobs) > 3:
            logger.info("... and %d more jobs", len(jobs) - 3)

        logger.info(sep)
        logger.info("Initial scraping completed!")
        logger.info(sep)

    # Now fetch detailed information for all jobs
    logger.info(sep)
    logger.info("Fetching detailed job information...")
    logger.info(sep)

    successful, failed = run_async_scraper(max_concurrent=5)

    logger.info("Jobs with details: %d", get_job_details_count())

    return jobs


if __name__ == "__main__":
    jobs = main()
