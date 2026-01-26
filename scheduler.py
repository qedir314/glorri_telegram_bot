"""
Scheduler for Glorri Jobs Bot.
Runs scraping and Telegram notifications every 6 hours.
"""

import sys
from datetime import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Load environment variables
load_dotenv()

# Import from src packages
from src.scraper import GlorriDriver, run_async_scraper
from src.database import insert_jobs_bulk, get_job_count
from src.bot import run_send_jobs, run_test_message


def scrape_and_notify():
    """Main job: scrape new jobs and send notifications."""
    print("\n" + "=" * 60)
    print(f"🕐 Job started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    try:
        # Step 1: Scrape new jobs
        print("\n--- Step 1: Scraping jobs ---")
        with GlorriDriver(headless=True) as driver:
            driver.wait_for_page_load(3)
            jobs = driver.scroll_until_days_old(target_days=7)
            
            # Save to database
            inserted, skipped = insert_jobs_bulk(jobs)
            print(f"✓ Inserted: {inserted} new jobs")
            print(f"✓ Skipped: {skipped} existing jobs")
            print(f"✓ Total in database: {get_job_count()}")
        
        # Step 2: Scrape job details for new jobs
        print("\n--- Step 2: Fetching job details ---")
        run_async_scraper(max_concurrent=5)
        
        # Step 3: Send new jobs to Telegram
        print("\n--- Step 3: Sending to Telegram ---")
        sent, failed = run_send_jobs()
        
        print("\n" + "=" * 60)
        print(f"✅ Job completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
    except Exception as e:
        print(f"✗ Error during scheduled job: {e}")


def run_scheduler(interval_minutes: int = 360):
    """Run the scheduler.
    
    Args:
        interval_minutes: Interval in minutes (default 360 = 6 hours)
    """
    print("=" * 60)
    print("🤖 Glorri Jobs Bot Scheduler")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Schedule: Every {interval_minutes} minutes")
    print("=" * 60)
    
    # Test Telegram connection first
    print("\n--- Testing Telegram connection ---")
    if not run_test_message():
        print("✗ Failed to connect to Telegram. Check your credentials.")
        print("Continuing anyway...")
    
    # Run immediately on start
    print("\n--- Running initial scrape ---")
    scrape_and_notify()
    
    # Set up scheduler
    scheduler = BlockingScheduler()
    
    # Schedule job at interval
    scheduler.add_job(
        scrape_and_notify,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id='scrape_and_notify',
        name=f'Scrape and notify every {interval_minutes} minutes',
        replace_existing=True
    )
    
    print("\n" + "=" * 60)
    print("📅 Scheduler is running. Press Ctrl+C to stop.")
    print(f"   Next run in {interval_minutes} minutes")
    print("=" * 60)
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n✓ Scheduler stopped")


def run_once():
    """Run scrape and notify once (for testing)."""
    print("=" * 60)
    print("🤖 Glorri Jobs Bot - Single Run")
    print("=" * 60)
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
            print("  (no arg): Run with 6-hour interval")
    else:
        # Run scheduler with 6-hour interval
        run_scheduler(interval_minutes=360)
