"""
Telegram Bot for sending Glorri job notifications.
Sends new job postings to a specified Telegram channel/chat.
"""

import os
import asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.constants import ParseMode
from database import get_unsent_jobs, mark_jobs_as_sent, get_unsent_jobs_count

# Load environment variables
load_dotenv()

# Telegram configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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
        print(f"✗ Failed to send job ID {job.get('id')}: {e}")
        return False


async def send_new_jobs() -> tuple:
    """
    Send all unsent jobs to Telegram.
    
    Returns:
        Tuple of (sent_count, failed_count)
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("✗ Telegram credentials not configured in .env")
        return 0, 0
    
    # Get unsent jobs
    jobs = get_unsent_jobs()
    
    if not jobs:
        print("✓ No new jobs to send")
        return 0, 0
    
    print(f"📤 Sending {len(jobs)} new jobs to Telegram...")
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    sent_ids = []
    failed_count = 0
    
    for job in jobs:
        success = await send_job_to_telegram(bot, job)
        if success:
            sent_ids.append(job['id'])
            print(f"✓ Sent: {job.get('title', 'Unknown')[:50]}")
        else:
            failed_count += 1
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)
    
    # Mark sent jobs in database
    if sent_ids:
        marked = mark_jobs_as_sent(sent_ids)
        print(f"✓ Marked {marked} jobs as sent in database")
    
    print(f"\n{'='*50}")
    print(f"✅ Telegram notification completed!")
    print(f"   Sent: {len(sent_ids)}")
    print(f"   Failed: {failed_count}")
    print(f"{'='*50}")
    
    return len(sent_ids), failed_count


async def send_test_message() -> bool:
    """
    Send a test message to verify bot configuration.
    
    Returns:
        True if successful, False otherwise
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("✗ Telegram credentials not configured in .env")
        return False
    
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🤖 <b>Glorri Jobs Bot</b>\n\n✓ Bot successfully configured!\n📋 Ready to send job notifications.",
            parse_mode=ParseMode.HTML
        )
        print("✓ Test message sent successfully!")
        return True
    except Exception as e:
        print(f"✗ Failed to send test message: {e}")
        return False


def run_send_jobs():
    """Run the send_new_jobs coroutine (wrapper for sync code)."""
    return asyncio.run(send_new_jobs())


def run_test_message():
    """Run the send_test_message coroutine (wrapper for sync code)."""
    return asyncio.run(send_test_message())


if __name__ == "__main__":
    print("=" * 50)
    print("Glorri Jobs Telegram Bot")
    print("=" * 50)
    
    # Test the bot
    print("\n--- Testing Bot Configuration ---")
    if run_test_message():
        print("\n--- Sending New Jobs ---")
        sent, failed = run_send_jobs()
