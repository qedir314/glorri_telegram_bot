"""
Main script for Glorri Jobs Scraper
Scrapes job listings from both jobs.glorri.az and jobsearch.az in parallel,
saves jobs to SQLite database, and fetches detailed job information.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import src.config  # noqa: F401  -- load .env + configure logging (must be first)

from src.scraper import (
    GlorriDriver,
    JobSearchAzDriver,
    run_async_scraper,
    run_jobsearch_async_scraper,
)
from src.database import insert_jobs_bulk, get_job_count, get_job_details_count

logger = logging.getLogger(__name__)


def _scrape_glorri() -> list:
    """Scrape job listings from jobs.glorri.az."""
    logger.info("=" * 50)
    logger.info("[Glorri] Starting scraper...")
    logger.info("=" * 50)

    with GlorriDriver(headless=False) as driver:
        driver.wait_for_page_load(3)
        logger.info("[Glorri] Scrolling to load jobs (until 7 days old)...")
        jobs = driver.scroll_until_days_old(target_days=7)
        logger.info("[Glorri] Loaded %d job listings", len(jobs))

        # Sample first 3 jobs
        for i, job in enumerate(jobs[:3], 1):
            logger.info("[Glorri] [%d] %s | %s | %s", i, job.title, job.company, job.location)
        if len(jobs) > 3:
            logger.info("[Glorri] ... and %d more jobs", len(jobs) - 3)

    return jobs


def _scrape_jobsearch() -> list:
    """Scrape job listings from jobsearch.az."""
    logger.info("=" * 50)
    logger.info("[JobSearch.az] Starting scraper...")
    logger.info("=" * 50)

    with JobSearchAzDriver(headless=False) as driver:
        driver.wait_for_page_load(3)
        logger.info("[JobSearch.az] Scrolling to load jobs (until 7 days old)...")
        jobs = driver.scroll_until_days_old(target_days=7)
        logger.info("[JobSearch.az] Loaded %d job listings", len(jobs))

        # Sample first 3 jobs
        for i, job in enumerate(jobs[:3], 1):
            logger.info("[JobSearch.az] [%d] %s | %s | %s", i, job.title, job.company, job.location)
        if len(jobs) > 3:
            logger.info("[JobSearch.az] ... and %d more jobs", len(jobs) - 3)

    return jobs


def main():
    """Main function to scrape both websites in parallel and save to database."""
    sep = "=" * 50
    logger.info(sep)
    logger.info("Glorri + JobSearch.az Parallel Jobs Scraper")
    logger.info("Both scrapers start simultaneously")
    logger.info(sep)

    # --- Step 1: Run both Selenium scrapers in parallel ---
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
                logger.info("[%s] Completed successfully with %d jobs", scraper_name, len(jobs))
            except Exception as e:
                logger.error("[%s] Scraper failed: %s", scraper_name, e, exc_info=True)
                scraper_errors.append(scraper_name)

    if scraper_errors:
        logger.warning("Some scrapers failed: %s", ", ".join(scraper_errors))

    # --- Step 2: Save all jobs to database ---
    logger.info(sep)
    logger.info("--- Saving %d total jobs to database ---", len(all_jobs))
    inserted, skipped = insert_jobs_bulk(all_jobs)
    logger.info("Inserted: %d new jobs", inserted)
    logger.info("Skipped: %d existing jobs", skipped)
    logger.info("Total jobs in database: %d", get_job_count())
    logger.info(sep)

    # Ensure SQLite has flushed the bulk insert before detail scrapers query
    time.sleep(1)

    # --- Step 3: Fetch detailed information for all jobs ---
    logger.info(sep)
    logger.info("Fetching detailed job information from both websites...")
    logger.info(sep)

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

    logger.info("Jobs with details: %d", get_job_details_count())
    logger.info(sep)
    logger.info("Full scraping pipeline completed!")
    logger.info(sep)

    return all_jobs


if __name__ == "__main__":
    jobs = main()
