"""
Main script for Glorri Jobs Scraper
Uses GlorriDriver to scrape job listings from https://jobs.glorri.az/
"""

from glorri_selenium import GlorriDriver


def main():
    """Main function to scrape Glorri jobs."""
    print("=" * 50)
    print("Glorri Jobs Scraper")
    print("Scrolling until last vacancy is 14 days old")
    print("=" * 50)
    
    # Create driver and run scraper
    with GlorriDriver(headless=False) as driver:
        # Wait for initial page load
        driver.wait_for_page_load(3)
        
        # Scroll until last vacancy is 14 days old
        print("\n--- Scrolling to load jobs (until 14 days old) ---")
        jobs = driver.scroll_until_days_old(target_days=14)
        
        # Print summary
        print(f"\n--- Loaded {len(jobs)} Job Listings ---")
        
        # Print first 10 jobs as sample
        for i, job in enumerate(jobs[:5], 1):
            print(f"\n[{i}] {job.title}")
            print(f"    Company: {job.company}")
            print(f"    Location: {job.location}")
            if job.posted_date:
                days_ago = driver.get_days_ago(job.posted_date)
                print(f"    Posted: {job.posted_date.strftime('%d-%m-%Y')} ({days_ago} days ago)")
            if job.job_url:
                print(f"    URL: {job.job_url}")
        
        if len(jobs) > 10:
            print(f"\n... and {len(jobs) - 10} more jobs")
        
        # Take a screenshot
        driver.take_screenshot("glorri_demo.png")
        
        print("\n" + "=" * 50)
        print("Scraping completed!")
        print("=" * 50)
        
        return jobs


if __name__ == "__main__":
    jobs = main()
