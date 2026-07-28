# 🎵 Telegram Music Downloader Bot (Self-Hosted)

An asynchronous, self-hosted Telegram Bot built in Python and Docker that allows you to search for music or paste URLs (YouTube, SoundCloud, etc.) to download high-quality MP3s directly inside Telegram. 

> **⚠️ Notice:** There is no public instance of this bot. To protect server resources and API limits, this repository is designed exclusively for **self-hosting**. To use this bot, you must deploy your own instance with your own `@BotFather` API token.

---

## 🚀 Features

- 🔍 **Interactive Music Search**: Displays up to 40 search results across multiple paginated interactive keyboard buttons (`<<`, `1 / 4`, `>>`).
- 🔗 **Direct URL & Download All**: Paste a video/audio link to extract audio instantly, or download an entire page of search results at once.
- 🏷️ **ID3 Tagging & Cover Art**: Automatically embeds track title, artist name, duration, and album thumbnail directly into the native Telegram audio player.
- 🐳 **Cloud & Docker Ready**: Includes automated anti-bot cloud bypasses and a built-in HTTP server (port 7860) for health check keep-alives on platforms like Back4App and Glitch.
- 🔒 **Private Access Control**: Built-in User ID filtering ensuring only authorized owners can interact with your bot instance.
- 🧹 **Auto-Cleanup**: Zero disk footprint—automatically deletes audio conversion files immediately after uploading to Telegram.

---

## 🛠️ Self-Hosting Installation & Setup

### 1. Generate Your Bot Credentials
1. Message **[@BotFather](https://t.me/BotFather)** on Telegram to create a new bot and get your API Token.
2. Message **[@userinfobot](https://t.me/userinfobot)** to retrieve your numeric Telegram User ID (used to restrict access to only yourself).
3. Create a `.env` file in the project root:

```env
TELEGRAM_BOT_TOKEN="your-telegram-bot-token-here"
ALLOWED_USER_ID="123456789" # Your numeric Telegram user ID
```

### 2. Run Locally (Python & FFmpeg Required)

```bash
# Install dependencies
pip install -r requirements.txt

# Start the bot
python bot.py
```

### 3. Deploy via Docker / Cloud Containers

This project is fully Dockerized and pre-configured for free cloud containers (such as Back4App Containers, Fly.io, or Render):

1. Connect your cloned GitHub repository to your container cloud provider.
2. Add your `TELEGRAM_BOT_TOKEN` and `ALLOWED_USER_ID` into the cloud platform's **Environment Variables** / Secrets dashboard.
3. Deploy! The included `Dockerfile` will automatically build Python 3.12 with FFmpeg and keep your bot online 24/7.
