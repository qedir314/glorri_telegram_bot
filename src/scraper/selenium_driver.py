"""
Selenium driver for accessing Glorri Jobs website (https://jobs.glorri.az/)
This module provides a GlorriDriver class to interact with the job listing website.
"""

import os
import logging
from selenium import webdriver

# Load .env before reading any env vars (safe for standalone imports)
import src.config  # noqa: F401
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    """Data class to represent a job listing."""
    title: str
    company: str
    location: str
    posted_date: Optional[datetime] = None
    deadline: Optional[str] = None
    job_url: Optional[str] = None
    views: Optional[str] = None


class GlorriDriver:
    """
    Selenium driver class for interacting with the Glorri Jobs website.
    
    Usage:
        driver = GlorriDriver()
        driver.start()
        jobs = driver.get_job_listings()
        driver.close()
    
    Or use as context manager:
        with GlorriDriver() as driver:
            jobs = driver.get_job_listings()
    """
    
    BASE_URL = os.getenv("BASE_URL", "https://google.com/")
    
    def __init__(self, headless: bool = True, timeout: int = 10):
        """
        Initialize the Glorri driver.
        
        Args:
            headless: Run browser in headless mode (no GUI). Default True.
            timeout: Default timeout for waiting elements in seconds.
        """
        self.headless = headless
        self.timeout = timeout
        self.driver = None
        self.wait = None
    
    def start(self):
        """Start the browser and navigate to the Glorri jobs website."""
        chrome_options = Options()
        
        if self.headless:
            chrome_options.add_argument("--headless")
        
        # Common options for stability
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        # Set user agent to avoid detection
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Initialize the driver
        # Check if running in Docker/Linux with system chromedriver
        import shutil
        system_driver_path = shutil.which("chromedriver") or "/usr/bin/chromedriver"
        system_chromium_path = shutil.which("chromium") or "/usr/bin/chromium"
        
        if os.path.exists(system_driver_path) and os.path.exists(system_chromium_path):
            logger.info("Using system Chromium at %s", system_chromium_path)
            logger.info("Using system ChromeDriver at %s", system_driver_path)
            chrome_options.binary_location = system_chromium_path
            service = Service(executable_path=system_driver_path)
        else:
            logger.info("Using WebDriverManager for Chrome")
            service = Service(ChromeDriverManager().install())

        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.wait = WebDriverWait(self.driver, self.timeout)
        
        # Navigate to the website
        self.driver.get(self.BASE_URL)
        logger.info("Connected to %s", self.BASE_URL)
        
        return self
    
    def close(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()
            self.driver = None
            logger.info("Browser closed")
    
    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
        return False
    
    def wait_for_page_load(self, delay: float = 2.0):
        """Wait for the page to load completely."""
        time.sleep(delay)
    
    def search_jobs(self, keyword: str = "", city: str = "") -> None:
        """
        Search for jobs using the search form.
        
        Args:
            keyword: Job title or keyword to search for.
            city: City to filter jobs by.
        """
        try:
            # Find and fill the keyword search input
            if keyword:
                keyword_input = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Vakansiya']"))
                )
                keyword_input.clear()
                keyword_input.send_keys(keyword)
                logger.info("Entered keyword: %s", keyword)
            
            # Find and fill the city input
            if city:
                city_input = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='Şəhər']"))
                )
                city_input.clear()
                city_input.send_keys(city)
                logger.info("Entered city: %s", city)
            
            # Click the search button
            search_button = self.wait.until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Axtar')]"))
            )
            search_button.click()
            logger.info("Search button clicked")
            
            # Wait for results to load
            self.wait_for_page_load()
            
        except TimeoutException as e:
            logger.error("Timeout while searching: %s", e)
    
    def get_job_listings(self, max_jobs: int = 20) -> List[JobListing]:
        """
        Get job listings from the current page.
        
        Args:
            max_jobs: Maximum number of jobs to retrieve.
            
        Returns:
            List of JobListing objects.
        """
        jobs = []
        
        try:
            # Wait for job cards to load
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/vacancies/']"))
            )
            
            # Find all job card elements
            job_cards = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancies/']")
            
            for card in job_cards[:max_jobs]:
                try:
                    # Extract job information
                    job_url = card.get_attribute("href")
                    
                    # Try to get title from h3 or similar heading
                    try:
                        title = card.find_element(By.TAG_NAME, "h3").text
                    except NoSuchElementException:
                        title = card.text.split('\n')[0] if card.text else "Unknown"
                    
                    # Try to extract other details
                    card_text = card.text.split('\n')
                    company = card_text[1] if len(card_text) > 1 else "Unknown"
                    location = card_text[2] if len(card_text) > 2 else "Unknown"
                    
                    job = JobListing(
                        title=title.strip(),
                        company=company.strip(),
                        location=location.strip(),
                        job_url=job_url
                    )
                    jobs.append(job)
                    
                except Exception as e:
                    logger.error("Error parsing job card: %s", e)
                    continue
            
            logger.info("Found %d job listings", len(jobs))
            
        except TimeoutException:
            logger.error("Timeout waiting for job listings")
        
        return jobs
    
    def scroll_to_load_more(self, scroll_count: int = 3, delay: float = 1.5):
        """
        Scroll down to load more jobs (infinite scroll).
        
        Args:
            scroll_count: Number of times to scroll.
            delay: Delay between scrolls in seconds.
        """
        for i in range(scroll_count):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(delay)
            logger.info("Scrolled %d/%d", i + 1, scroll_count)
    
    def parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse date string from Glorri website.
        
        Handles formats:
        - "DD-MM-YYYY" (e.g., "24-01-2026")
        - "Dünən" (yesterday)
        - "Bugün" (today)
        
        Args:
            date_str: Date string from the website.
            
        Returns:
            datetime object or None if parsing fails.
        """
        if not date_str:
            return None
        
        date_str = date_str.strip()
        today = datetime.now()
        
        # Handle relative dates in Azerbaijani
        if date_str.lower() == "dünən":
            return today - timedelta(days=1)
        elif date_str.lower() == "bugün":
            return today
        
        # Try DD-MM-YYYY format
        date_pattern = r"(\d{2})-(\d{2})-(\d{4})"
        match = re.search(date_pattern, date_str)
        if match:
            day, month, year = match.groups()
            try:
                return datetime(int(year), int(month), int(day))
            except ValueError:
                pass
        
        return None
    
    def get_days_ago(self, date: datetime) -> int:
        """
        Calculate how many days ago a date was.
        
        Args:
            date: datetime object to check.
            
        Returns:
            Number of days ago (0 for today, 1 for yesterday, etc.)
        """
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        target = date.replace(hour=0, minute=0, second=0, microsecond=0)
        return (today - target).days
    
    def get_last_visible_date(self) -> Tuple[Optional[datetime], Optional[str]]:
        """
        Get the date of the last visible job listing.
        
        Returns:
            Tuple of (datetime object, original date string) or (None, None) if not found.
        """
        try:
            # Find all job cards
            job_cards = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancies/']")
            
            if not job_cards:
                return None, None
            
            # Get the last card's text
            last_card = job_cards[-1]
            card_text = last_card.text
            
            # Look for date pattern in the card text
            lines = card_text.split('\n')
            
            for line in lines:
                line = line.strip()
                # Check for DD-MM-YYYY pattern
                if re.match(r"\d{2}-\d{2}-\d{4}", line):
                    parsed_date = self.parse_date(line)
                    if parsed_date:
                        return parsed_date, line
                # Check for "Dünən" or "Bugün"
                elif line.lower() in ["dünən", "bugün"]:
                    parsed_date = self.parse_date(line)
                    if parsed_date:
                        return parsed_date, line
            
            return None, None
            
        except Exception as e:
            logger.error("Error getting last visible date: %s", e)
            return None, None
    
    def scroll_until_days_old(self, target_days: int = 14, max_scrolls: int = 100, delay: float = 1.5) -> List[JobListing]:
        """
        Scroll until the last vacancy is at least target_days old.
        
        Args:
            target_days: Stop scrolling when last vacancy is this many days old (default 14).
            max_scrolls: Maximum number of scroll attempts to prevent infinite loops.
            delay: Delay between scrolls in seconds.
            
        Returns:
            List of all job listings loaded during scrolling.
        """
        logger.info("Scrolling until last vacancy is %d days old...", target_days)
        
        scroll_count = 0
        previous_height = 0
        previous_job_count = 0
        
        while scroll_count < max_scrolls:
            # Scroll to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(delay)
            scroll_count += 1
            
            # Check if page height changed (new content loaded)
            current_height = self.driver.execute_script("return document.body.scrollHeight")
            
            # Get current job cards count and URLs
            job_cards = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancies/']")
            current_job_count = len(job_cards)
            
            # Get the last visible date
            last_date, date_str = self.get_last_visible_date()
            
            if last_date:
                days_ago = self.get_days_ago(last_date)
                status_msg = "Scroll %d: Last vacancy = %s (%d days ago), %d jobs loaded" % (
                    scroll_count, date_str, days_ago, current_job_count)
            else:
                days_ago = 0
                status_msg = "Scroll %d: %d jobs loaded" % (scroll_count, current_job_count)

            logger.info(status_msg)
            
            # Check if reached target days
            if last_date and days_ago >= target_days:
                logger.info("Reached target! Last vacancy is %d days old (>= %d)", days_ago, target_days)
                break
            
            # Check if we've reached the end of content
            if current_height == previous_height and current_job_count == previous_job_count:
                logger.warning("No more content to load")
                break
            
            previous_height = current_height
            previous_job_count = current_job_count
        
        if scroll_count >= max_scrolls:
            logger.warning("Reached maximum scroll limit (%d)", max_scrolls)
        
        # Return all job listings
        return self.get_all_job_listings()
    
    def get_all_job_listings(self) -> List[JobListing]:
        """
        Get all currently loaded job listings.
        
        Returns:
            List of JobListing objects.
        """
        jobs = []
        
        try:
            # Find all job card elements
            job_cards = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/vacancies/']")

            skipped_no_url = 0
            skipped_few_lines = 0
            skipped_parse_error = 0
            
            for card in job_cards:
                try:
                    # Skip cards that don't look like job listings (e.g., carousel items)
                    job_url = card.get_attribute("href")
                    if not job_url or "/vacancies/" not in job_url:
                        skipped_no_url += 1
                        continue
                    
                    card_text = card.text
                    lines = [l.strip() for l in card_text.split('\n') if l.strip()]
                    
                    if len(lines) < 2:
                        skipped_few_lines += 1
                        logger.debug("Skipped card (few lines): %s", job_url)
                        continue
                    
                    # Try to get title from h3
                    try:
                        title = card.find_element(By.TAG_NAME, "h3").text.strip()
                    except NoSuchElementException:
                        title = lines[0] if lines else "Unknown"
                    
                    # Parse company and location
                    company = "Unknown"
                    location = "Unknown"
                    posted_date = None
                    
                    for line in lines:
                        # Check for date
                        parsed = self.parse_date(line)
                        if parsed:
                            posted_date = parsed
                        # Check for company/location pattern (contains ●)
                        elif "●" in line:
                            parts = line.split("●")
                            company = parts[0].strip()
                            location = parts[1].strip() if len(parts) > 1 else "Unknown"
                    
                    job = JobListing(
                        title=title,
                        company=company,
                        location=location,
                        posted_date=posted_date,
                        job_url=job_url
                    )
                    jobs.append(job)
                    
                except Exception as e:
                    skipped_parse_error += 1
                    logger.debug("Skipped card (parse error): %s", e)
                    continue

            skipped_total = skipped_no_url + skipped_few_lines + skipped_parse_error
            logger.info("Total job listings loaded: %d (skipped: %d no-url, %d few-lines, %d parse-errors)",
                        len(jobs), skipped_no_url, skipped_few_lines, skipped_parse_error)
            
        except Exception as e:
            logger.error("Error getting job listings: %s", e)
        
        return jobs
    
    def get_job_details(self, job_url: str) -> dict:
        """
        Navigate to a job detail page and extract information.
        
        Args:
            job_url: URL of the job detail page.
            
        Returns:
            Dictionary with job details.
        """
        details = {}
        
        try:
            self.driver.get(job_url)
            self.wait_for_page_load()
            
            # Get page title (job title)
            try:
                details['title'] = self.driver.find_element(By.TAG_NAME, "h1").text
            except NoSuchElementException:
                details['title'] = "Unknown"
            
            # Get job description
            try:
                description_elem = self.driver.find_element(
                    By.XPATH, "//h2[contains(text(), 'Təsvir')]/following-sibling::*"
                )
                details['description'] = description_elem.text
            except NoSuchElementException:
                details['description'] = ""
            
            # Get requirements
            try:
                requirements_elem = self.driver.find_element(
                    By.XPATH, "//h2[contains(text(), 'Tələblər')]/following-sibling::*"
                )
                details['requirements'] = requirements_elem.text
            except NoSuchElementException:
                details['requirements'] = ""
            
            logger.info("Retrieved details for: %s", details.get('title', 'Unknown'))
            
        except Exception as e:
            logger.error("Error getting job details: %s", e)
        
        return details
    
    def take_screenshot(self, filename: str = "glorri_screenshot.png"):
        """Take a screenshot of the current page."""
        if self.driver:
            self.driver.save_screenshot(filename)
            logger.info("Screenshot saved: %s", filename)
    
    def get_current_url(self) -> str:
        """Get the current page URL."""
        return self.driver.current_url if self.driver else ""
    
    def navigate_to(self, url: str):
        """Navigate to a specific URL."""
        if self.driver:
            self.driver.get(url)
            self.wait_for_page_load()
