"""
Main script for Glorri Jobs Scraper
Uses GlorriDriver to scrape job listings from https://jobs.glorri.az/
Saves jobs to SQLite database and fetches detailed job information
"""

from glorri_selenium import GlorriDriver
from database import insert_jobs_bulk, get_job_count, get_job_details_count
from async_scraper import run_async_scraper


def main():
    """Main function to scrape Glorri jobs and save to database."""
    print("=" * 50)
    print("Glorri Jobs Scraper")
    print("Scrolling until last vacancy is 7 days old")
    print("=" * 50)
    
    # Create driver and run scraper
    with GlorriDriver(headless=False) as driver:
        # Wait for initial page load
        driver.wait_for_page_load(3)
        
        # Scroll until last vacancy is 7 days old
        print("\n--- Scrolling to load jobs (until 7 days old) ---")
        jobs = driver.scroll_until_days_old(target_days=7)
        
        # Print summary
        print(f"\n--- Loaded {len(jobs)} Job Listings ---")
        
        # Save jobs to database
        print("\n--- Saving jobs to database ---")
        inserted, skipped = insert_jobs_bulk(jobs)
        print(f"✓ Inserted: {inserted} new jobs")
        print(f"✓ Skipped: {skipped} existing jobs")
        print(f"✓ Total jobs in database: {get_job_count()}")
        
        # Print first 5 jobs as sample
        for i, job in enumerate(jobs[:3], 1):
            print(f"\n[{i}] {job.title}")
            print(f"    Company: {job.company}")
            print(f"    Location: {job.location}")
            if job.posted_date:
                days_ago = driver.get_days_ago(job.posted_date)
                print(f"    Posted: {job.posted_date.strftime('%d-%m-%Y')} ({days_ago} days ago)")
            if job.job_url:
                print(f"    URL: {job.job_url}")
        
        if len(jobs) > 5:
            print(f"\n... and {len(jobs) - 5} more jobs")
        
        print("\n" + "=" * 50)
        print("Initial scraping completed!")
        print("=" * 50)
    
    # Now fetch detailed information for all jobs
    print("\n" + "=" * 50)
    print("Fetching detailed job information...")
    print("=" * 50)
    
    successful, failed = run_async_scraper(max_concurrent=5)
    
    print(f"\n✓ Jobs with details: {get_job_details_count()}")
    
    return jobs


if __name__ == "__main__":
    jobs = main()
