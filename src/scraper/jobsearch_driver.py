"""
Selenium driver for accessing JobSearch.az website (https://jobsearch.az/)
This module provides a JobSearchAzDriver class to interact with the job listing website.
Uses the same JobListing dataclass for compatibility with existing database/bot modules.
"""

import json
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
from typing import List, Optional, Dict

# Reuse the same JobListing dataclass from the glorri driver
from .selenium_driver import JobListing

logger = logging.getLogger(__name__)


class JobSearchAzDriver:
    """
    Selenium driver class for interacting with the JobSearch.az website.
    
    Usage:
        driver = JobSearchAzDriver()
        driver.start()
        jobs = driver.get_job_listings()
        driver.close()
    
    Or use as context manager:
        with JobSearchAzDriver() as driver:
            jobs = driver.scroll_until_days_old(target_days=7)
    """
    
    BASE_URL = os.getenv("JOBSEARCH_BASE_URL", "https://jobsearch.az/")
    
    def __init__(self, headless: bool = True, timeout: int = 10):
        """
        Initialize the JobSearch.az driver.
        
        Args:
            headless: Run browser in headless mode (no GUI). Default True.
            timeout: Default timeout for waiting elements in seconds.
        """
        self.headless = headless
        self.timeout = timeout
        self.driver = None
        self.wait = None
    
    def start(self):
        """Start the browser and navigate to the JobSearch.az website."""
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
    
    def _find_scrollable_vacancy_container(self):
        """Find the scrollable container element that holds the vacancy list in the center.

        On JobSearch.az, vacancies are in a center column that may have its own
        scroll container separate from the left/right sidebars. This method locates
        that container so we can scroll within it to load more vacancies, instead
        of scrolling the entire browser window.

        Returns:
            WebElement of the scrollable container, or None if not found.
        """
        # Strategy 1: Find the parent container of known job card elements
        try:
            job_patterns = ['/job/', '/vacancy/', '/vacancies/', '/elan/', '/announcement/']
            for href_pattern in job_patterns:
                cards = self.driver.find_elements(By.CSS_SELECTOR, f"a[href*='{href_pattern}']")
                if cards:
                    # Walk up from the first card to find a scrollable ancestor
                    ancestor = cards[0]
                    for _ in range(10):
                        try:
                            ancestor = ancestor.find_element(By.XPATH, "..")
                            overflow_y = ancestor.value_of_css_property("overflow-y")
                            if overflow_y in ("auto", "scroll"):
                                logger.debug("Found scrollable vacancy container via job card ancestor")
                                return ancestor
                        except Exception:
                            break
                    break
        except Exception:
            pass

        # Strategy 2: Look for <main> element with overflow
        try:
            main = self.driver.find_element(By.TAG_NAME, "main")
            overflow_y = main.value_of_css_property("overflow-y")
            if overflow_y in ("auto", "scroll"):
                logger.debug("Found scrollable <main> element")
                return main
        except NoSuchElementException:
            pass

        # Strategy 3: Look for common center content area classes with overflow
        center_selectors = [
            "[class*='v-main__wrap']",
            "[class*='container']",
            "div[data-v-]",
        ]
        for selector in center_selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for el in elements:
                    overflow_y = el.value_of_css_property("overflow-y")
                    if overflow_y in ("auto", "scroll") and el.size['height'] > 300:
                        logger.debug("Found scrollable container via selector '%s'", selector)
                        return el
            except Exception:
                continue

        logger.debug("No scrollable vacancy container found")
        return None

    def _find_job_card_elements(self):
        """
        Find all job card/link elements on the page.

        JobSearch.az typically has job listings as clickable elements (often <a> tags)
        that link to individual job detail pages. We try multiple selector strategies
        and union results to avoid missing cards due to inconsistent URL patterns.

        Returns:
            List of WebElement objects representing job cards.
        """
        all_elements = []
        seen_hrefs = set()

        # Strategy 1: Look for <a> tags containing known job URL patterns
        job_patterns = ['/job/', '/vacancy/', '/vacancies/', '/elan/', '/announcement/']
        for href_pattern in job_patterns:
            elements = self.driver.find_elements(By.CSS_SELECTOR, f"a[href*='{href_pattern}']")
            for el in elements:
                href = el.get_attribute("href")
                if href and href not in seen_hrefs:
                    seen_hrefs.add(href)
                    all_elements.append(el)
                    logger.debug("Found job card via pattern '%s': %s", href_pattern, href)

        if all_elements:
            logger.debug("Found %d unique job cards from URL patterns", len(all_elements))
            return all_elements

        # Strategy 2: Look for <a> tags that have numeric IDs in their href
        elements = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='id=']")
        for el in elements:
            href = el.get_attribute("href")
            if href and href not in seen_hrefs:
                seen_hrefs.add(href)
                all_elements.append(el)

        if all_elements:
            logger.debug("Found %d job cards via 'id=' pattern", len(all_elements))
            return all_elements

        # Strategy 3: Fallback - all <a> tags within <main> content area
        try:
            main_content = self.driver.find_element(By.TAG_NAME, "main")
            elements = main_content.find_elements(By.TAG_NAME, "a")
            if elements:
                logger.debug("Found %d links in <main> content (fallback)", len(elements))
                return elements
        except NoSuchElementException:
            pass

        # Strategy 4: Last resort - all <a> tags on the page
        elements = self.driver.find_elements(By.TAG_NAME, "a")
        logger.debug("Last resort fallback: found %d total <a> tags", len(elements))
        return elements
    
    def _parse_job_card(self, card) -> Optional[JobListing]:
        """
        Parse a single job card element into a JobListing.
        
        Args:
            card: WebElement representing a job card.
            
        Returns:
            JobListing object or None if parsing fails.
        """
        try:
            job_url = card.get_attribute("href")
            if not job_url:
                return None
            
            # Skip non-job URLs
            job_url_lower = job_url.lower()
            is_job_url = any(pattern in job_url_lower for pattern in 
                           ['/job/', '/vacancy/', '/vacancies/', '/elan/', '/announcement/', 
                            'jobsearch.az', 'job=', 'vacancy=', 'vacancies='])
            if not is_job_url:
                return None
            
            card_text = card.text.strip()
            if not card_text or len(card_text) < 3:
                return None
            
            lines = [l.strip() for l in card_text.split('\n') if l.strip()]
            
            if len(lines) < 2:
                return None
            
            # Try to identify title, company, location from the lines
            title = lines[0]
            company = "Unknown"
            location = "Unknown"
            posted_date = None
            
            for i, line in enumerate(lines):
                # Skip first line (title)
                if i == 0:
                    continue
                # Second line is typically company
                if i == 1:
                    company = line
                elif i == 2:
                    location = line
            
            # If we have more lines, try to find company/location by known patterns
            for line in lines:
                if company == "Unknown" and ('şirkət' not in line.lower() and 'company' not in line.lower()):
                    # Second line is often company name
                    pass
            
            # Try to find location in text
            location_keywords = ['Bakı', 'Gəncə', 'Sumqayıt', 'Mingəçevir', 'Naxçıvan', 
                               'Şəki', 'Lənkəran', 'remote', 'Remote', 'Baku']
            for line in lines:
                for kw in location_keywords:
                    if kw.lower() in line.lower():
                        location = line
                        break
            
            job = JobListing(
                title=title,
                company=company,
                location=location,
                posted_date=posted_date,
                job_url=job_url
            )
            return job
            
        except Exception as e:
            logger.debug("Error parsing job card: %s", e)
            return None
    
    def get_all_job_listings(self) -> List[JobListing]:
        """
        Get all currently loaded job listings from the page.

        Uses a single JavaScript call to extract vacancy data from the DOM,
        avoiding the per-element round-trips of Python WebElement iteration.

        Returns:
            List of JobListing objects.
        """
        try:
            jobs = self._extract_jobs_via_js()
            if jobs:
                return jobs
        except Exception as e:
            logger.warning("JS extraction failed (%s), falling back to Python", e)

        # Fallback: Python WebElement iteration
        jobs = []
        seen_urls = set()
        skipped_parse = 0
        skipped_duplicate = 0

        try:
            job_cards = self._find_job_card_elements()

            for card in job_cards:
                try:
                    job = self._parse_job_card(card)
                    if not job:
                        skipped_parse += 1
                    elif job.job_url not in seen_urls:
                        seen_urls.add(job.job_url)
                        jobs.append(job)
                    else:
                        skipped_duplicate += 1
                except Exception:
                    skipped_parse += 1
                    continue

            logger.info("Total job listings loaded: %d (skipped: %d parse, %d duplicate)",
                        len(jobs), skipped_parse, skipped_duplicate)

        except Exception as e:
            logger.error("Error getting job listings: %s", e)

        return jobs

    def _extract_jobs_via_js(self) -> List[JobListing]:
        """Extract job listings using a single JavaScript call for speed.

        Instead of iterating through WebElements in Python (each ``.text`` /
        ``.get_attribute()`` is a browser round-trip), we execute one JS
        snippet that finds all vacancy links, extracts their data, and
        returns JSON — all inside the browser.
        """
        js_code = """
        const jobs = [];
        const seen = new Set();
        const patterns = ['/job/', '/vacancy/', '/vacancies/', '/elan/', '/announcement/'];

        const links = document.querySelectorAll('a[href]');
        for (const link of links) {
            const href = link.getAttribute('href');
            if (!href || seen.has(href)) continue;

            let isJob = false;
            for (const p of patterns) {
                if (href.includes(p)) { isJob = true; break; }
            }
            if (!isJob && !href.includes('jobsearch.az')) continue;

            const text = link.textContent.trim();
            if (!text || text.length < 3) continue;

            const lines = text.split('\\n').map(l => l.trim()).filter(l => l);
            if (lines.length < 2) continue;

            seen.add(href);
            // Normalize relative URLs to absolute
            const fullUrl = href.startsWith('/') ? 'https://jobsearch.az' + href : href;
            jobs.push({
                url: fullUrl,
                title: lines[0],
                company: lines[1] || 'Unknown',
                location: lines[2] || 'Unknown'
            });
        }
        return JSON.stringify(jobs);
        """

        result = self.driver.execute_script(js_code)
        if not result:
            return []

        raw_jobs = json.loads(result)
        jobs = []
        for rj in raw_jobs:
            job = JobListing(
                title=rj.get('title', 'Unknown'),
                company=rj.get('company', 'Unknown'),
                location=rj.get('location', 'Unknown'),
                posted_date=None,
                job_url=rj.get('url', '')
            )
            jobs.append(job)

        logger.info("JS extraction: %d job listings found", len(jobs))
        return jobs
    
    def scroll_to_load_more(self, scroll_count: int = 3, delay: float = 1.5):
        """
        Scroll the center vacancy list to load more jobs (infinite scroll).

        On JobSearch.az, the vacancy list is in a center column that may have
        its own scroll container separate from the left/right sidebars. We
        scroll within that container instead of the whole browser window to
        properly trigger lazy loading and avoid disturbing sidebars.

        Args:
            scroll_count: Number of times to scroll.
            delay: Delay between scrolls in seconds.
        """
        container = self._find_scrollable_vacancy_container()

        if container:
            logger.info("Scrolling within center vacancy container...")
            for i in range(scroll_count):
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight;", container
                )
                time.sleep(delay)
                logger.info("Scrolled container %d/%d", i + 1, scroll_count)
        else:
            logger.info("No center container found, scrolling entire page...")
            for i in range(scroll_count):
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(delay)
                logger.info("Scrolled window %d/%d", i + 1, scroll_count)
    
    def scroll_until_days_old(
        self,
        target_days: int = 7,
        max_scrolls: int = 30,
        delay: float = 2.0
    ) -> List[JobListing]:
        """
        Scroll the center vacancy list to load more jobs on the current page.

        Instead of navigating through paginated URLs (?page=2, ?page=3, ...),
        this stays on a single page and repeatedly scrolls the center vacancy
        container to trigger infinite (or lazy) loading of additional vacancies.
        
        Args:
            target_days: Number of days to look back (approximated as pages).
            max_scrolls: Maximum number of scroll attempts to prevent infinite loops.
            delay: Delay between scrolls in seconds.
            
        Returns:
            List of all job listings loaded.
        """
        logger.info("JobSearch.az: Starting on single page, scrolling center container "
                     "up to %d times to approximate %d days...", max_scrolls, target_days)
        
        # Navigate to the vacancies page once
        url = f"{self.BASE_URL}vacancies"
        logger.info("JobSearch.az: Navigating to %s", url)
        self.driver.get(url)
        time.sleep(delay)
        self.wait_for_page_load(1.0)

        # Locate the center scrollable container for vacancies
        container = self._find_scrollable_vacancy_container()
        if container:
            logger.info("JobSearch.az: Found center vacancy container — scrolling within it")
        else:
            logger.info("JobSearch.az: No center container found, scrolling entire page")

        all_jobs = []
        seen_urls = set()
        scroll_count = 0
        previous_height = 0
        previous_job_count = 0
        no_change_streak = 0
        
        while scroll_count < max_scrolls:
            # Scroll the center container (or window as fallback)
            if container:
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight;", container
                )
                current_height = self.driver.execute_script(
                    "return arguments[0].scrollHeight", container
                )
            else:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                current_height = self.driver.execute_script("return document.body.scrollHeight")
            
            time.sleep(delay)
            scroll_count += 1
            
            # Parse newly visible job cards
            page_jobs = self.get_all_job_listings()
            new_count = 0
            for job in page_jobs:
                if job.job_url not in seen_urls:
                    seen_urls.add(job.job_url)
                    all_jobs.append(job)
                    new_count += 1
            
            current_job_count = len(all_jobs)
            height_delta = abs(current_height - previous_height) if previous_height > 0 else 0
            logger.info("JobSearch.az: Scroll %d — %d new jobs (total: %d) | "
                        "height: %d → %d (Δ%d) | container: %s",
                        scroll_count, new_count, current_job_count,
                        previous_height, current_height, height_delta,
                        "yes" if container else "no")
            
            # Check if we've reached the end of content
            # Require 3 consecutive scrolls with NO change before stopping
            if (current_height == previous_height
                and current_job_count == previous_job_count):
                no_change_streak += 1
                if no_change_streak >= 3:
                    logger.warning("JobSearch.az: No new content for %d scrolls — stopping",
                                   no_change_streak)
                    break
            else:
                no_change_streak = 0
            
            previous_height = current_height
            previous_job_count = current_job_count
        
        if scroll_count >= max_scrolls:
            logger.warning("JobSearch.az: Reached maximum scroll limit (%d)", max_scrolls)
        
        logger.info("JobSearch.az: Finished — %d total unique jobs from single page "
                     "(%d scrolls)", len(all_jobs), scroll_count)
        return all_jobs
    
    def take_screenshot(self, filename: str = "jobsearch_screenshot.png"):
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
