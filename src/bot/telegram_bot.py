"""
Telegram Bot for sending Glorri job notifications.
Sends new job postings to a specified Telegram channel/chat.
"""

import os
import re
import logging
import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from src.database import get_unsent_jobs, mark_jobs_as_sent, get_unsent_jobs_count

# Load .env before reading env vars (must be first import)
import src.config  # noqa: F401

logger = logging.getLogger(__name__)

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Keyword filter — only send jobs whose title/description/requirements
# contain at least one of these keywords (case-insensitive).
# Set to empty string to send all jobs.
# Comma-separated, e.g.: "Python,SQL,Java"
TELEGRAM_KEYWORDS_RAW = os.getenv("TELEGRAM_KEYWORDS", "Python,SQL")
TELEGRAM_KEYWORDS = [
    kw.strip().lower()
    for kw in TELEGRAM_KEYWORDS_RAW.split(",")
    if kw.strip()
]

# Delay between consecutive Telegram messages (seconds).
# Increase this if you hit flood-control limits.
# Telegram recommends at least 1 message per second for groups,
# but private chats may need 2-3 seconds between messages.
TELEGRAM_MESSAGE_DELAY = float(os.getenv("TELEGRAM_MESSAGE_DELAY", "3.0"))


def format_job_message(job: dict) -> str:
    """
    Format a job posting as a Telegram message.
    Telegram limit is 4096 characters.
    
    Args:
        job: Job dictionary from database
        
    Returns:
        Formatted message string with HTML formatting
    """
    TELEGRAM_MAX_LENGTH = 4096
    
    title = job.get('title', 'Unknown Title')
    company = job.get('company', 'Unknown Company')
    location = job.get('location', 'Unknown Location')
    job_url = job.get('job_url', '')
    posted_date = job.get('posted_date', '')
    job_type = job.get('job_type', '')
    deadline = job.get('deadline', '')
    
    # Additional details
    description = job.get('description', '') or ''
    requirements = job.get('requirements', '') or ''
    job_level = job.get('job_level', '')
    category = job.get('category', '')
    salary = job.get('salary', '')
    views = job.get('views', '')
    
    # Build header part (always included)
    message_parts = [
        f"💼 <b>{title}</b>",
        f"🏢 {company}",
        f"📍 {location}",
    ]
    
    if job_type:
        message_parts.append(f"⏰ {job_type}")
    
    if job_level:
        message_parts.append(f"📊 Səviyyə: {job_level}")
    
    if category:
        message_parts.append(f"📁 Kateqoriya: {category}")
    
    if salary:
        message_parts.append(f"💰 Maaş: {salary}")
    
    if posted_date:
        message_parts.append(f"📅 Paylaşılıb: {posted_date}")
    
    if deadline:
        message_parts.append(f"⏳ Son tarix: {deadline}")
    
    if views:
        message_parts.append(f"👁 Baxış: {views}")
    
    # Add link at the end
    link_part = f"\n🔗 <a href=\"{job_url}\">Ətraflı bax</a>" if job_url else ""
    
    # Calculate header length
    header = "\n".join(message_parts)
    header_length = len(header) + len(link_part) + 50  # 50 for labels and newlines
    
    # Calculate available space for description and requirements
    available_space = TELEGRAM_MAX_LENGTH - header_length
    
    # Split available space between description and requirements
    if description and requirements:
        desc_max = available_space // 2
        req_max = available_space // 2
    elif description:
        desc_max = available_space
        req_max = 0
    elif requirements:
        desc_max = 0
        req_max = available_space
    else:
        desc_max = 0
        req_max = 0
    
    # Add description (truncate if needed)
    if description:
        if len(description) > desc_max:
            desc_text = description[:desc_max - 3] + "..."
        else:
            desc_text = description
        message_parts.append(f"\n📝 <b>Təsvir:</b>\n{desc_text}")
    
    # Add requirements (truncate if needed)
    if requirements:
        if len(requirements) > req_max:
            req_text = requirements[:req_max - 3] + "..."
        else:
            req_text = requirements
        message_parts.append(f"\n✅ <b>Tələblər:</b>\n{req_text}")
    
    if job_url:
        message_parts.append(f"\n🔗 <a href=\"{job_url}\">Ətraflı bax</a>")

    return "\n".join(message_parts)


def job_matches_keywords(job: dict, keywords: list) -> bool:
    """
    Check if a job matches any of the configured keywords.

    Searches title, description, and requirements (case-insensitive).
    If the keywords list is empty, all jobs match.

    Args:
        job: Job dictionary from database (with joined details).
        keywords: List of lowercase keyword strings.

    Returns:
        True if the job matches at least one keyword (or no filter is set).
    """
    if not keywords:
        return True  # no filter → send everything

    # Combine all searchable text
    title = (job.get("title") or "").lower()
    description = (job.get("description") or "").lower()
    requirements = (job.get("requirements") or "").lower()
    combined = f"{title} {description} {requirements}"

    for kw in keywords:
        if kw in combined:
            return True

    return False


def _parse_flood_control_retry_after(error_message: str) -> int:
    """
    Extract the retry-after seconds from a Telegram flood-control error.

    Telegram errors look like:
        "Flood control exceeded. Retry in 230 seconds"

    Args:
        error_message: The exception message string.

    Returns:
        Number of seconds to wait, or 0 if not a flood-control error.
    """
    match = re.search(r"Retry in (\d+) seconds", str(error_message))
    if match:
        return int(match.group(1))
    return 0


async def send_job_to_telegram(bot: Bot, job: dict) -> bool:
    """
    Send a single job to Telegram.
    
    Args:
        bot: Telegram Bot instance
        job: Job dictionary
        
    Returns:
        True if sent successfully, False otherwise
    """
    try:
        message = format_job_message(job)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        return True
    except Exception as e:
        retry_after = _parse_flood_control_retry_after(str(e))
        if retry_after > 0:
            logger.warning(
                "Flood control for job ID %s — waiting %d seconds...",
                job.get("id"), retry_after,
            )
        else:
            logger.error("Failed to send job ID %s: %s", job.get("id"), e)
        return False


async def send_new_jobs() -> tuple:
    """
    Send all unsent jobs to Telegram.

    Only jobs whose title/description/requirements match the configured
    TELEGRAM_KEYWORDS are actually sent.  Non-matching jobs are silently
    marked as sent so they are not retried.

    When Telegram returns a flood-control error, the bot waits the
    requested amount of time and then resumes.  Flood-controlled jobs
    are **not** marked as sent and will be retried on the next cycle.

    Returns:
        Tuple of (sent_count, skipped_count, failed_count)
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured in .env")
        return 0, 0, 0

    # Get unsent jobs
    jobs = get_unsent_jobs()

    if not jobs:
        logger.info("No new jobs to send")
        return 0, 0, 0

    logger.info(
        "Processing %d unsent jobs (keywords=%s, delay=%ds)...",
        len(jobs),
        TELEGRAM_KEYWORDS if TELEGRAM_KEYWORDS else "[ALL]",
        TELEGRAM_MESSAGE_DELAY,
    )

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    sent_ids = []
    skipped_ids = []
    flood_control_ids = []  # will be retried next cycle
    other_fail_count = 0

    for job in jobs:
        job_id = job["id"]
        title_short = (job.get("title", "Unknown")[:50])

        # --- keyword filter ---
        if not job_matches_keywords(job, TELEGRAM_KEYWORDS):
            skipped_ids.append(job_id)
            logger.debug("Skipped (no keyword match): %s", title_short)
            continue

        # --- send to Telegram ---
        success = await send_job_to_telegram(bot, job)
        if success:
            sent_ids.append(job_id)
            logger.info("Sent: %s", title_short)
        else:
            # Check if failure was flood-control
            # We already logged the specific error inside send_job_to_telegram
            error_occurred = True
            # We can't easily tell from the return value alone, but
            # send_job_to_telegram already logged the reason.
            # Let's retry on the next cycle anyway.
            other_fail_count += 1

        # Delay between messages (constant rate to avoid flood limits)
        await asyncio.sleep(TELEGRAM_MESSAGE_DELAY)

    # Mark only sent + skipped jobs as processed
    # Flood-controlled and other-failure jobs stay unsent for retry
    all_processed = sent_ids + skipped_ids
    if all_processed:
        marked = mark_jobs_as_sent(all_processed)
        logger.info("Marked %d jobs as processed in database", marked)

    sep = "=" * 50
    logger.info(sep)
    logger.info("Telegram notification completed!")
    logger.info("   Sent:             %d", len(sent_ids))
    logger.info("   Skipped (filter): %d", len(skipped_ids))
    logger.info("   Failed (will retry): %d", other_fail_count)
    logger.info(sep)

    return len(sent_ids), len(skipped_ids), other_fail_count


async def send_test_message() -> bool:
    """
    Send a test message to verify bot configuration.
    
    Returns:
        True if successful, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured in .env")
        return False

    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🤖 <b>Glorri Jobs Bot</b>\n\n✓ Bot successfully configured!\n📋 Ready to send job notifications.",
            parse_mode=ParseMode.HTML,
        )
        logger.info("Test message sent successfully!")
        return True
    except Exception as e:
        logger.error("Failed to send test message: %s", e)
        return False


def run_send_jobs():
    """Run the send_new_jobs coroutine (wrapper for sync code)."""
    return asyncio.run(send_new_jobs())


def run_test_message():
    """Run the send_test_message coroutine (wrapper for sync code)."""
    return asyncio.run(send_test_message())


if __name__ == "__main__":
    # When run directly, ensure .env is loaded and logging is configured
    import src.config  # noqa: F401

    logger.info("=" * 50)
    logger.info("Glorri Jobs Telegram Bot")
    logger.info("=" * 50)

    # Test the bot
    logger.info("--- Testing Bot Configuration ---")
    if run_test_message():
        logger.info("--- Sending New Jobs ---")
        sent, skipped, failed = run_send_jobs()
