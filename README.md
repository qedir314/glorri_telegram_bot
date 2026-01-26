# Glorri Jobs Telegram Bot

A Telegram bot that scrapes job listings from [Glorri Jobs](https://jobs.glorri.az/) and sends notifications every 6 hours.

## Features

- 🔍 Scrapes job listings using Selenium
- 📊 Stores jobs in SQLite database
- 📝 Fetches detailed job information asynchronously
- 📤 Sends new job notifications to Telegram
- ⏰ Runs automatically every 6 hours

## Project Structure

```
glorri_telegram_bot/
├── src/
│   ├── scraper/          # Web scraping modules
│   │   ├── selenium_driver.py
│   │   └── async_scraper.py
│   ├── database/         # Database operations
│   │   └── db.py
│   └── bot/              # Telegram bot
│       └── telegram_bot.py
├── data/                 # Database storage
├── config/               # Configuration examples
│   └── .env.example
├── .env                  # Your configuration (not in git)
├── main.py               # Run once
├── scheduler.py          # Run scheduled
└── requirements.txt
```

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp config/.env.example .env
   # Edit .env with your Telegram credentials
   ```

3. **Create Telegram Bot:**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow instructions
   - Copy the bot token to `.env`

## Usage

**Run once:**
```bash
python scheduler.py --once
```

**Test with 2-minute interval:**
```bash
python scheduler.py --test
```

**Run in production (6-hour interval):**
```bash
python scheduler.py
```

## Configuration

Edit `.env` file:
```env
BASE_URL=https://jobs.glorri.az/
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```
