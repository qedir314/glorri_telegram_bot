# Glorri Jobs Telegram Bot

A Telegram bot that scrapes job listings from [Glorri Jobs](https://jobs.glorri.az/) and sends notifications every 3 hours.

## Features

- 🔍 Scrapes job listings using Selenium
- 📊 Stores jobs in SQLite database
- 📝 Fetches detailed job information asynchronously
- 📤 Sends new job notifications to Telegram
- ⏰ Runs automatically every 3 hours
- 🐳 Docker support for easy deployment

## Project Structure

```
glorri_telegram_bot/
├── src/
│   ├── scraper/          # Web scraping modules
│   ├── database/         # Database operations
│   └── bot/              # Telegram bot
├── data/                 # Database storage
├── config/               # Configuration examples
├── Dockerfile
├── docker-compose.yml
├── main.py               # Run once
├── scheduler.py          # Run scheduled
└── requirements.txt
```

## Local Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment:**
   ```bash
   cp config/.env.example .env
   # Edit .env with your Telegram credentials
   ```

3. **Run:**
   ```bash
   python scheduler.py
   ```

## Docker Deployment (DigitalOcean)

### Option 1: Using Docker Compose

```bash
# Clone the repo
git clone https://github.com/qedir314/glorri_telegram_bot.git
cd glorri_telegram_bot

# Configure environment
cp config/.env.example .env
nano .env  # Add your Telegram credentials

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Option 2: Using Docker directly

```bash
# Build image
docker build -t glorri-bot .

# Run container
docker run -d \
  --name glorri-telegram-bot \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  glorri-bot
```

### DigitalOcean Droplet Setup

1. Create a Droplet (Ubuntu 22.04, 1GB RAM minimum)
2. SSH into the droplet
3. Install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
4. Follow Docker Compose instructions above

## Configuration

Edit `.env` file:
```env
BASE_URL=https://jobs.glorri.az/
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

