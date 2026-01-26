"""
Async scraper for fetching detailed job information from Glorri job pages.
Uses aiohttp for async HTTP requests and BeautifulSoup for HTML parsing.
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import Optional, Dict, List
import re
from database import get_jobs_without_details, insert_job_details, get_job_details_count


# Request headers to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def fetch_page(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """
    Fetch a single page asynchronously.
    
    Args:
        session: aiohttp client session
        url: URL to fetch
        
    Returns:
        HTML content or None if failed
    """
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status == 200:
                return await response.text()
            else:
                print(f"✗ Failed to fetch {url}: Status {response.status}")
                return None
    except asyncio.TimeoutError:
        print(f"✗ Timeout fetching {url}")
        return None
    except Exception as e:
        print(f"✗ Error fetching {url}: {e}")
        return None


def parse_job_details(html: str, url: str) -> Dict:
    """
    Parse job details from HTML content.
    
    Args:
        html: HTML content of the job page
        url: URL of the job (for reference)
        
    Returns:
        Dictionary with job details
    """
    soup = BeautifulSoup(html, 'html.parser')
    details = {}
    
    # Get job description (Təsvir section)
    # Structure: <h3>Təsvir</h3> followed by <div class="description-html">
    try:
        # Find h3 with text "Təsvir"
        description_heading = None
        for h3 in soup.find_all('h3'):
            if h3.get_text(strip=True) == 'Təsvir':
                description_heading = h3
                break
        
        if description_heading:
            # Find the next sibling with class "description-html"
            description_container = description_heading.find_next_sibling('div', class_='description-html')
            if description_container:
                details['description'] = description_container.get_text(separator='\n', strip=True)
            else:
                # Try just next sibling
                next_elem = description_heading.find_next_sibling()
                if next_elem:
                    details['description'] = next_elem.get_text(separator='\n', strip=True)
    except Exception as e:
        details['description'] = None
    
    # Get requirements (Tələblər section)
    # Structure: <h3>Tələblər</h3> followed by <div class="description-html">
    try:
        requirements_heading = None
        for h3 in soup.find_all('h3'):
            if h3.get_text(strip=True) == 'Tələblər':
                requirements_heading = h3
                break
        
        if requirements_heading:
            requirements_container = requirements_heading.find_next_sibling('div', class_='description-html')
            if requirements_container:
                details['requirements'] = requirements_container.get_text(separator='\n', strip=True)
            else:
                next_elem = requirements_heading.find_next_sibling()
                if next_elem:
                    details['requirements'] = next_elem.get_text(separator='\n', strip=True)
    except Exception as e:
        details['requirements'] = None
    
    # Get category (Kateqoriya)
    # Structure: <h3>Kateqoriya</h3> followed by <span>
    try:
        category_heading = None
        for h3 in soup.find_all('h3'):
            if h3.get_text(strip=True) == 'Kateqoriya':
                category_heading = h3
                break
        
        if category_heading:
            category_span = category_heading.find_next_sibling('span')
            if category_span:
                details['category'] = category_span.get_text(strip=True)
            else:
                # Try next element
                next_elem = category_heading.find_next_sibling()
                if next_elem:
                    details['category'] = next_elem.get_text(strip=True)
    except Exception as e:
        details['category'] = None
    
    # Parse sidebar metadata (Vakansiya haqqında)
    # Structure: <h3>Vakansiya haqqında</h3> with parent containing <div class="flex justify-between">
    try:
        vacancy_heading = None
        for h3 in soup.find_all('h3'):
            if h3.get_text(strip=True) == 'Vakansiya haqqında':
                vacancy_heading = h3
                break
        
        if vacancy_heading:
            # Get parent container
            parent = vacancy_heading.parent
            if parent:
                # Find all flex justify-between divs (label-value pairs)
                info_rows = parent.find_all('div', class_=lambda x: x and 'flex' in x and 'justify-between' in x)
                
                for row in info_rows:
                    children = row.find_all(recursive=False)
                    if len(children) >= 2:
                        label = children[0].get_text(strip=True)
                        value = children[1].get_text(strip=True)
                        
                        # Map labels to fields
                        if 'Son tarix' in label:
                            details['deadline'] = value
                        elif 'Vakansiya növü' in label:
                            details['job_type'] = value
                        elif 'Vəzifə dərəcəsi' in label:
                            details['job_level'] = value
                        elif 'Təhsil' in label:
                            details['education'] = value
    except Exception as e:
        pass
    
    # Fallback for job type if not found in sidebar
    if not details.get('job_type'):
        page_text = soup.get_text()
        job_type_patterns = ['Tam ştat', 'Yarım ştat', 'Frilans', 'Müqavilə', 'Təcrübə', 'Daimi']
        for pattern in job_type_patterns:
            if pattern in page_text:
                details['job_type'] = pattern
                break
    
    # Try to extract views count
    # Views is displayed as a number in a flex container with an eye icon
    try:
        # Look for the views pattern: flex container with just a number (e.g., "208")
        # The view count is typically displayed near the date in the header
        views_containers = soup.find_all('div', class_=lambda x: x and 'flex' in x and 'items-center' in x)
        for container in views_containers:
            # Look for a p tag with just a number
            p_tags = container.find_all('p')
            for p in p_tags:
                text = p.get_text(strip=True)
                # Check if it's just a number (views count is a plain number like "208" or "1.2K")
                if re.match(r'^[\d,\.]+[KkMm]?$', text):
                    # Convert "1.2K" style to number
                    text = text.replace(',', '')
                    if 'K' in text.upper():
                        details['views'] = int(float(text.upper().replace('K', '')) * 1000)
                    elif 'M' in text.upper():
                        details['views'] = int(float(text.upper().replace('M', '')) * 1000000)
                    else:
                        details['views'] = int(text)
                    break
            if details.get('views'):
                break
        else:
            details['views'] = None
    except Exception:
        details['views'] = None
    
    # Try to extract salary (often not present)
    try:
        all_text = soup.get_text(separator=' ')
        salary_match = re.search(r'(\d+(?:\s*-\s*\d+)?)\s*(?:AZN|manat)', all_text, re.IGNORECASE)
        if salary_match:
            details['salary'] = salary_match.group(0)
        else:
            details['salary'] = None
    except Exception:
        details['salary'] = None
    
    return details


async def scrape_job_details(job: dict, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> bool:
    """
    Scrape details for a single job.
    
    Args:
        job: Job dictionary with id and job_url
        session: aiohttp client session
        semaphore: Semaphore to limit concurrent requests
        
    Returns:
        True if successful, False otherwise
    """
    async with semaphore:
        job_id = job['id']
        job_url = job['job_url']
        
        # Fetch the page
        html = await fetch_page(session, job_url)
        if not html:
            return False
        
        # Parse the details
        details = parse_job_details(html, job_url)
        
        # Save to database
        success = insert_job_details(
            job_id=job_id,
            job_url=job_url,
            description=details.get('description'),
            requirements=details.get('requirements'),
            job_type=details.get('job_type'),
            job_level=details.get('job_level'),
            education=details.get('education'),
            category=details.get('category'),
            salary=details.get('salary'),
            deadline=details.get('deadline'),
            views=details.get('views')
        )
        
        if success:
            print(f"✓ Scraped details for job ID {job_id}")
        else:
            print(f"⚠ Job ID {job_id} details already exist")
        
        # Increased delay to avoid rate limiting (429 errors)
        await asyncio.sleep(1.5)
        
        return success


async def scrape_all_job_details(max_concurrent: int = 5) -> tuple:
    """
    Scrape details for all jobs that don't have details yet.
    
    Args:
        max_concurrent: Maximum number of concurrent requests
        
    Returns:
        Tuple of (successful_count, failed_count)
    """
    # Get jobs without details
    jobs = get_jobs_without_details()
    
    if not jobs:
        print("✓ All jobs already have details scraped")
        return 0, 0
    
    print(f"📋 Found {len(jobs)} jobs without details")
    print(f"🚀 Starting async scraping with {max_concurrent} concurrent requests...")
    
    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(max_concurrent)
    
    successful = 0
    failed = 0
    
    # Create aiohttp session
    async with aiohttp.ClientSession() as session:
        # Create tasks for all jobs
        tasks = [scrape_job_details(job, session, semaphore) for job in jobs]
        
        # Execute all tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        for result in results:
            if isinstance(result, Exception):
                print(f"✗ Task failed with exception: {result}")
                failed += 1
            elif result:
                successful += 1
            else:
                failed += 1
    
    print(f"\n{'='*50}")
    print(f"✅ Scraping completed!")
    print(f"   Successful: {successful}")
    print(f"   Failed: {failed}")
    print(f"   Total details in DB: {get_job_details_count()}")
    print(f"{'='*50}")
    
    return successful, failed


def run_async_scraper(max_concurrent: int = 5) -> tuple:
    """
    Run the async scraper (wrapper for sync code).
    
    Args:
        max_concurrent: Maximum number of concurrent requests
        
    Returns:
        Tuple of (successful_count, failed_count)
    """
    return asyncio.run(scrape_all_job_details(max_concurrent))


if __name__ == "__main__":
    print("=" * 50)
    print("Glorri Job Details Async Scraper")
    print("=" * 50)
    
    successful, failed = run_async_scraper(max_concurrent=5)
