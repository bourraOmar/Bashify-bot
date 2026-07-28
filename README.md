# 🎵 Telegram Music Downloader Bot

A personal Telegram Bot built in Python that allows you to search for music or paste URLs (YouTube, SoundCloud, etc.) to download high-quality MP3s directly inside Telegram.

## 🚀 Features

- 🔍 **Search Music**: Type any song title or artist name (e.g. `Cheb Reda Sbabi L'amour`) to get interactive search results.
- 🔗 **Direct URL Download**: Paste a video/audio link to instantly extract and download audio.
- 🏷️ **ID3 Tagging & Cover Art**: Automatically attaches title, artist name, duration, and thumbnail to the native Telegram audio player.
- 🔒 **Security Access Control**: Optional owner restriction so only your Telegram User ID can use the bot.
- 🧹 **Auto-Cleanup**: Automatically cleans up temporary files after sending to save disk space.

---

## 🛠️ How to Run

### 1. Configure Credentials
Make sure your `.env` file contains your Bot Token from `@BotFather`:

```env
TELEGRAM_BOT_TOKEN=8608855272:AAGgVOC8LwtqMui9FAlId7BgcTdl8mhS7Lc

# Optional: Set your numeric Telegram User ID from @userinfobot to restrict usage to only you
ALLOWED_USER_ID=
```

### 2. Launch the Bot

Run the bot script using the virtual environment:

```powershell
.venv\Scripts\python.exe bot.py
```

---

## 📱 How to Use in Telegram

1. Open Telegram and search for [@DownBashaBot](https://t.me/DownBashaBot).
2. Click **Start** or send `/start`.
3. Type any song name (e.g., `Cheb Reda Sbabi L'amour`) or paste a YouTube/SoundCloud link.
4. Click on a result button to download and play your MP3 audio directly in Telegram!
