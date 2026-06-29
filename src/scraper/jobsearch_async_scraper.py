"""
Async scraper for fetching detailed job information from JobSearch.az job pages.
Uses aiohttp for async HTTP requests.

Since jobsearch.az is a Nuxt.js SPA, the detail content is NOT rendered in
server-side HTML (only skeleton placeholders are present). Instead, vacancy data
is embedded in a ``window.__NUXT__`` JavaScript payload. This scraper extracts
and parses that payload in pure Python — no Node.js dependency required.
"""

import asyncio
import logging
import re
import aiohttp
from bs4 import BeautifulSoup
from typing import Optional, Dict, List, Any, Tuple
from src.database import get_jobs_without_details, insert_job_details, get_job_details_count

logger = logging.getLogger(__name__)

# Request headers to mimic a browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def fetch_page(session: aiohttp.ClientSession, url: str, max_retries: int = 3) -> Optional[str]:
    """Fetch a single page asynchronously with retry logic for rate limiting."""
    for attempt in range(max_retries):
        try:
            async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    return await response.text()
                elif response.status == 429:
                    wait_time = (attempt + 1) * 10
                    logger.warning("Rate limited (429), waiting %ds before retry...", wait_time)
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error("Failed to fetch %s: Status %d", url, response.status)
                    return None
        except asyncio.TimeoutError:
            logger.error("Timeout fetching %s", url)
            return None
        except Exception as e:
            logger.error("Error fetching %s: %s", url, e)
            return None

    logger.error("Max retries exceeded for %s", url)
    return None


# =====================================================================
#  NUXT Payload Parser — Pure Python
# =====================================================================
#
# The window.__NUXT__ payload has the format:
#
#   window.__NUXT__=(function(a,b,c,...){ return {BIG_OBJECT} })(v0,v1,v2,...)
#
# It is a self-invoking function whose parameters act as a compression
# dictionary.  Short variable names (a, b, $J, sQ, …) map to primitive
# values (numbers, strings, booleans) listed in the invocation arguments.
# The function body returns a large JS object literal whose values may
# reference those variables.
#
# To extract data we:
#   1. Parse the parameter names and the invocation argument values.
#   2. Build a  var_name → python_value  substitution map.
#   3. Walk the JS object text (string-aware) to locate specific fields.
#   4. Resolve each field's value — either an inline literal or a variable
#      looked up in the map.
# =====================================================================


def _find_matching_char(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Find the position of the matching closing character.

    Correctly skips over quoted strings and nested pairs.

    Args:
        text: Source text.
        start: Position of the opening character.
        open_ch / close_ch: The bracket pair, e.g. ``{`` / ``}``.

    Returns:
        Index of the matching *close_ch*, or ``-1`` if not found.
    """
    depth = 0
    in_str = False
    quote: Optional[str] = None
    i = start
    while i < len(text):
        c = text[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == quote:
                in_str = False
        else:
            if c in '"\'':
                in_str = True
                quote = c
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def _extract_js_string_at(text: str, pos: int) -> Tuple[str, int]:
    """Extract a JS string starting at *pos* (must point to the opening quote).

    Returns:
        ``(string_content_without_quotes, position_after_closing_quote)``
    """
    quote = text[pos]
    i = pos + 1
    while i < len(text):
        if text[i] == '\\':
            i += 2
        elif text[i] == quote:
            return text[pos + 1:i], i + 1
        else:
            i += 1
    # Unterminated string — return what we have
    return text[pos + 1:], len(text)


def _unescape_js_string(s: str) -> str:
    """Convert JS escape sequences (``\\n``, ``\\u002F``, …) to real characters."""
    result: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '\\' and i + 1 < n:
            nxt = s[i + 1]
            if nxt == 'n':
                result.append('\n'); i += 2
            elif nxt == 'r':
                result.append('\r'); i += 2
            elif nxt == 't':
                result.append('\t'); i += 2
            elif nxt in '"\'\\':
                result.append(nxt); i += 2
            elif nxt == '/':
                result.append('/'); i += 2
            elif nxt == 'u' and i + 5 < n:
                try:
                    result.append(chr(int(s[i + 2:i + 6], 16))); i += 6
                except ValueError:
                    result.append(s[i]); i += 1
            elif nxt == 'x' and i + 3 < n:
                try:
                    result.append(chr(int(s[i + 2:i + 4], 16))); i += 4
                except ValueError:
                    result.append(s[i]); i += 1
            else:
                result.append(nxt); i += 2
        else:
            result.append(s[i]); i += 1
    return ''.join(result)


def _tokenize_js_args(text: str) -> List[str]:
    """Tokenize the comma-separated invocation arguments of the NUXT function.

    Each argument is a primitive: number, quoted string, boolean, or null.
    """
    tokens: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]

        # Skip whitespace and commas
        if c in ' \t\r\n,':
            i += 1
            continue

        # Double-quoted string
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            tokens.append(text[i:j]); i = j; continue

        # Single-quoted string
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                elif text[j] == "'":
                    j += 1
                    break
                else:
                    j += 1
            tokens.append(text[i:j]); i = j; continue

        # Number (including negatives and decimals like -.012)
        if c.isdigit() \
           or (c == '-' and i + 1 < n and (text[i + 1].isdigit() or text[i + 1] == '.')) \
           or (c == '.' and i + 1 < n and text[i + 1].isdigit()):
            j = i + 1
            while j < n and (text[j].isdigit() or text[j] in '.eE+-'):
                j += 1
            tokens.append(text[i:j]); i = j; continue

        # Keywords
        if text[i:i + 6] == 'void 0':
            tokens.append('null'); i += 6; continue
        if text[i:i + 5] == 'false':
            tokens.append('false'); i += 5; continue
        if text[i:i + 4] == 'true':
            tokens.append('true'); i += 4; continue
        if text[i:i + 4] == 'null':
            tokens.append('null'); i += 4; continue

        # Identifier (shouldn't normally appear in args, but handle gracefully)
        if c.isalpha() or c in '_$':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in '_$'):
                j += 1
            tokens.append(text[i:j]); i = j; continue

        i += 1  # skip unknown char

    return tokens


def _parse_js_token(token: str) -> Any:
    """Convert a single JS token string into a Python value."""
    if token == 'true':
        return True
    if token == 'false':
        return False
    if token in ('null', 'undefined'):
        return None
    if (token.startswith('"') and token.endswith('"')) or \
       (token.startswith("'") and token.endswith("'")):
        return _unescape_js_string(token[1:-1])
    try:
        if '.' in token or 'e' in token.lower():
            return float(token)
        return int(token)
    except ValueError:
        return token  # return raw string if unparseable


def _build_nuxt_var_map(script_text: str) -> Tuple[Dict[str, Any], str]:
    """Parse the NUXT self-invoking function and build a variable map.

    Returns:
        ``(var_map, function_body_text)`` where *var_map* maps each
        parameter name to its resolved Python value.
    """
    # 1. Extract function parameter names  →  function(a,b,c,...){
    func_match = re.search(r'function\(([^)]+)\)\s*\{', script_text)
    if not func_match:
        return {}, ''

    param_names = [p.strip() for p in func_match.group(1).split(',')]
    brace_pos = func_match.end() - 1  # points to the opening {

    # 2. Find the matching } that closes the function body
    body_end = _find_matching_char(script_text, brace_pos, '{', '}')
    if body_end < 0:
        return {}, ''

    body = script_text[brace_pos + 1:body_end]  # text between { and }

    # 3. After the body: expect  )(ARGS)
    remaining = script_text[body_end + 1:]
    args_open = re.match(r'\)\s*\(', remaining)
    if not args_open:
        return {}, body

    args_start = body_end + 1 + args_open.end()
    args_end = script_text.rindex(')')       # the very last ) in the script
    args_text = script_text[args_start:args_end]

    # 4. Tokenize and parse argument values
    arg_tokens = _tokenize_js_args(args_text)

    var_map: Dict[str, Any] = {}
    for idx, name in enumerate(param_names):
        if idx < len(arg_tokens):
            var_map[name] = _parse_js_token(arg_tokens[idx])

    logger.debug("NUXT var map: %d params, %d args resolved", len(param_names), len(var_map))
    return var_map, body


def _find_field_in_js(text: str, field_name: str, target_depth: Optional[int] = None) -> int:
    """Find a JS property name in object text, **skipping** string contents
    and optionally ensuring we only match at a specific nesting depth.

    Returns the position immediately after the ``field_name:`` (i.e. the
    start of the value), or ``-1`` if not found.
    """
    target = field_name + ':'
    target_len = len(target)
    i = 0
    n = len(text)
    depth = 0

    while i < n:
        c = text[i]

        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1

        # Skip over string literals entirely
        if c in '"\'':
            quote = c
            i += 1
            while i < n:
                if text[i] == '\\':
                    i += 2
                elif text[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            continue

        # Check for a match at the current position
        if (target_depth is None or depth == target_depth) and text[i:i + target_len] == target:
            # Make sure it's a standalone property name (not the tail of a longer name)
            if i == 0 or not (text[i - 1].isalnum() or text[i - 1] in '_$'):
                return i + target_len
        i += 1

    return -1


def _resolve_value(text: str, pos: int, var_map: Dict[str, Any]) -> Any:
    """Resolve the JS value at position *pos*.

    Handles inline string / number / boolean / null literals,
    variable references (looked up in *var_map*), and returns raw text
    for objects ``{…}`` and arrays ``[…]``.
    """
    # Skip whitespace
    while pos < len(text) and text[pos] in ' \t\r\n':
        pos += 1
    if pos >= len(text):
        return None

    c = text[pos]

    # String literal
    if c in '"\'':
        content, _ = _extract_js_string_at(text, pos)
        return _unescape_js_string(content)

    # Object → return raw text (caller can drill into it)
    if c == '{':
        end = _find_matching_char(text, pos, '{', '}')
        return text[pos:end + 1] if end > 0 else None

    # Array → return raw text
    if c == '[':
        end = _find_matching_char(text, pos, '[', ']')
        return text[pos:end + 1] if end > 0 else None

    # Number
    num_match = re.match(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text[pos:])
    if num_match:
        s = num_match.group()
        return float(s) if ('.' in s or 'e' in s.lower()) else int(s)

    # Identifier → variable reference, boolean, or null
    id_match = re.match(r'[a-zA-Z_$][a-zA-Z0-9_$]*', text[pos:])
    if id_match:
        name = id_match.group()
        if name == 'true':
            return True
        if name == 'false':
            return False
        if name in ('null', 'undefined'):
            return None
        return var_map.get(name)

    return None


# =====================================================================
#  Vacancy Data Extraction
# =====================================================================

def _extract_nuxt_vacancy(html: str) -> Optional[Dict]:
    """Extract vacancy details from the ``__NUXT__`` payload in *html*.

    Navigates to ``state.modules.vacancies.tab_data.vacancy`` inside the
    NUXT payload and extracts description, category, deadline, salary, and
    view count.
    """
    # ---- 1. Locate the __NUXT__ <script> tag ----
    soup = BeautifulSoup(html, 'html.parser')
    script_text: Optional[str] = None
    for script in soup.find_all('script'):
        if script.string and '__NUXT__' in script.string:
            script_text = script.string
            break
    if not script_text:
        logger.debug("No __NUXT__ script found in page")
        return None

    # ---- 2. Build the variable substitution map ----
    var_map, body = _build_nuxt_var_map(script_text)
    if not body:
        logger.warning("Could not parse __NUXT__ function structure")
        return None

    # ---- 3. Find  tab_data:{…}  in the NUXT body ----
    td_pos = _find_field_in_js(body, 'tab_data')
    if td_pos < 0:
        logger.debug("tab_data not found in NUXT body")
        return None

    # Skip to the opening brace of the tab_data object
    while td_pos < len(body) and body[td_pos] in ' \t\r\n':
        td_pos += 1
    if td_pos >= len(body) or body[td_pos] != '{':
        return None

    td_end = _find_matching_char(body, td_pos, '{', '}')
    if td_end < 0:
        return None
    tab_data_text = body[td_pos:td_end + 1]

    # ---- 4. Find  vacancy:{…}  inside tab_data ----
    vac_pos = _find_field_in_js(tab_data_text, 'vacancy')
    if vac_pos < 0:
        logger.debug("vacancy field not found in tab_data")
        return None

    vac_value = _resolve_value(tab_data_text, vac_pos, var_map)
    if not isinstance(vac_value, str) or not vac_value.startswith('{'):
        logger.debug("vacancy value is not an object")
        return None

    vacancy_text = vac_value

    # ---- 5. Extract individual fields from the vacancy object ----
    details: Dict[str, Any] = {}

    # --- Description  (the "text" field contains combined HTML) ---
    text_pos = _find_field_in_js(vacancy_text, 'text', target_depth=1)
    if text_pos > 0:
        text_value = _resolve_value(vacancy_text, text_pos, var_map)
        if isinstance(text_value, str) and len(text_value) > 10:
            text_soup = BeautifulSoup(text_value, 'html.parser')
            full_text = text_soup.get_text(separator='\n', strip=True)
            desc, reqs = _split_description_requirements(full_text)
            details['description'] = desc or full_text
            if reqs:
                details['requirements'] = reqs

    # --- Category ---
    cat_pos = _find_field_in_js(vacancy_text, 'category', target_depth=1)
    if cat_pos > 0:
        cat_value = _resolve_value(vacancy_text, cat_pos, var_map)
        if isinstance(cat_value, str) and cat_value.startswith('{'):
            title_pos = _find_field_in_js(cat_value, 'title')
            if title_pos > 0:
                title_val = _resolve_value(cat_value, title_pos, var_map)
                if isinstance(title_val, str):
                    details['category'] = title_val

    # --- Deadline ---
    dl_pos = _find_field_in_js(vacancy_text, 'deadline_at', target_depth=1)
    if dl_pos > 0:
        dl_val = _resolve_value(vacancy_text, dl_pos, var_map)
        if isinstance(dl_val, str) and len(dl_val) >= 10:
            details['deadline'] = dl_val[:10]   # "2026-07-28T…" → "2026-07-28"

    # --- Salary ---
    sal_pos = _find_field_in_js(vacancy_text, 'salary', target_depth=1)
    if sal_pos > 0:
        sal_val = _resolve_value(vacancy_text, sal_pos, var_map)
        if isinstance(sal_val, (int, float)) and sal_val > 0:
            details['salary'] = f"{int(sal_val)} AZN"
        elif isinstance(sal_val, str) and sal_val.strip():
            details['salary'] = sal_val.strip()

    # --- Views ---
    vc_pos = _find_field_in_js(vacancy_text, 'v_count', target_depth=1)
    if vc_pos > 0:
        vc_val = _resolve_value(vacancy_text, vc_pos, var_map)
        if isinstance(vc_val, (int, float)):
            details['views'] = int(vc_val)

    # --- Job type / Education (heuristic from description text) ---
    if details.get('description'):
        _extract_text_metadata(details)

    return details if details else None


# =====================================================================
#  Helper: split description / requirements
# =====================================================================

def _split_description_requirements(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a combined vacancy text blob into description and requirements.

    Looks for well-known Azerbaijani / English section headings.
    """
    req_markers = [
        'Namizədə olan tələblər',
        'Tələblər:',
        'Tələblər',
        'Namizədə tələblər',
        'Requirements:',
        'Requirements',
        'Tələb olunan bacarıqlar',
    ]
    desc_markers = [
        'Vəzifə və öhdəliklər',
        'Vəzifə öhdəlikləri',
        'Öhdəliklər:',
        'Öhdəliklər',
        'İş vəzifələri',
        'Responsibilities',
        'İş haqqında',
        'İş şəraiti',
    ]

    req_start = -1
    for marker in req_markers:
        idx = text.find(marker)
        if idx >= 0:
            req_start = idx
            break

    desc_start = -1
    for marker in desc_markers:
        idx = text.find(marker)
        if idx >= 0:
            desc_start = idx
            break

    if req_start >= 0 and desc_start >= 0:
        if req_start < desc_start:
            return text[desc_start:].strip(), text[req_start:desc_start].strip()
        else:
            return text[desc_start:req_start].strip(), text[req_start:].strip()
    elif req_start >= 0:
        before = text[:req_start].strip() if req_start > 0 else None
        return before, text[req_start:].strip()
    elif desc_start >= 0:
        return text[desc_start:].strip(), None

    # No recognizable headings — return all text as description
    return text, None


def _extract_text_metadata(details: Dict) -> None:
    """Heuristically extract job_type, education, etc. from the description text."""
    combined = (details.get('description', '') + '\n'
                + details.get('requirements', ''))
    lower = combined.lower()

    if not details.get('job_type'):
        patterns = [
            ('tam ştat', 'Tam ştat'), ('full-time', 'Full-time'),
            ('full time', 'Full-time'), ('yarım ştat', 'Yarım ştat'),
            ('part-time', 'Part-time'), ('part time', 'Part-time'),
            ('frilans', 'Frilans'), ('freelance', 'Freelance'),
            ('müqavilə', 'Müqavilə'), ('contract', 'Contract'),
            ('remote', 'Remote'), ('uzaqdan', 'Uzaqdan'),
            ('hibrid', 'Hibrid'), ('hybrid', 'Hybrid'),
        ]
        for kw, label in patterns:
            if kw in lower:
                details['job_type'] = label
                break

    if not details.get('education'):
        patterns = [
            ('ali təhsil', 'Ali'), ('bakalavr', 'Bakalavr'),
            ('magistr', 'Magistr'), ('orta təhsil', 'Orta'),
            ('natamam ali', 'Natamam ali'), ('bachelor', 'Bachelor'),
            ('master', 'Master'),
        ]
        for kw, label in patterns:
            if kw in lower:
                details['education'] = label
                break


# =====================================================================
#  Public API  —  parse_job_details
# =====================================================================

def parse_job_details(html: str, url: str) -> Dict:
    """Parse job details from a JobSearch.az HTML page.

    Primary strategy: extract from the ``__NUXT__`` payload.
    Fallback: use ``<meta>`` tags for a partial description.
    """
    details: Dict[str, Any] = {}

    # --- Primary: NUXT payload extraction ---
    nuxt_data = _extract_nuxt_vacancy(html)
    if nuxt_data:
        details.update(nuxt_data)
        logger.debug("Extracted %d fields from NUXT for %s", len(nuxt_data), url)

    # --- Fallback: meta tags ---
    if not details.get('description'):
        soup = BeautifulSoup(html, 'html.parser')
        og = soup.find('meta', attrs={'property': 'og:description'})
        if og and og.get('content'):
            details['description'] = og['content'].replace('\xa0', ' ')
            logger.debug("Used og:description fallback for %s", url)

    return details


# =====================================================================
#  Async Scraping Infrastructure  (unchanged)
# =====================================================================

async def scrape_job_details(job: dict, session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> bool:
    """Scrape details for a single job from JobSearch.az."""
    async with semaphore:
        job_id = job['id']
        job_url = job['job_url']

        html = await fetch_page(session, job_url)
        if not html:
            return False

        details = parse_job_details(html, job_url)

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
            logger.info("JobSearch.az: Scraped details for job ID %d", job_id)
        else:
            logger.warning("JobSearch.az: Job ID %d details already exist", job_id)

        await asyncio.sleep(1)
        return success


async def scrape_all_job_details(max_concurrent: int = 2) -> tuple:
    """Scrape details for all jobs that don't have details yet."""
    jobs = get_jobs_without_details(url_pattern="jobsearch.az")

    if not jobs:
        logger.info("JobSearch.az: All jobs already have details scraped")
        return 0, 0

    logger.info("JobSearch.az: Found %d jobs without details", len(jobs))
    logger.info("JobSearch.az: Starting async scraping with %d concurrent requests...", max_concurrent)

    semaphore = asyncio.Semaphore(max_concurrent)
    successful = 0
    failed = 0

    async with aiohttp.ClientSession() as session:
        tasks = [scrape_job_details(job, session, semaphore) for job in jobs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("JobSearch.az: Task failed with exception: %s", result)
                failed += 1
            elif result:
                successful += 1
            else:
                failed += 1

    sep = "=" * 50
    logger.info(sep)
    logger.info("JobSearch.az scraping completed!")
    logger.info("   Successful: %d", successful)
    logger.info("   Failed: %d", failed)
    logger.info("   Total details in DB: %d", get_job_details_count())
    logger.info(sep)

    return successful, failed


def run_jobsearch_async_scraper(max_concurrent: int = 5) -> tuple:
    """Run the JobSearch.az async scraper (wrapper for sync code)."""
    return asyncio.run(scrape_all_job_details(max_concurrent))


if __name__ == "__main__":
    import src.config  # noqa: F401
    sep = "=" * 50
    logger.info(sep)
    logger.info("JobSearch.az Job Details Async Scraper")
    logger.info(sep)
    successful, failed = run_jobsearch_async_scraper(max_concurrent=5)
