import os
import re
import glob
import html
import logging
import asyncio
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Logging configuration
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Set up FFmpeg path
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(SCRIPT_DIR, "bin")

# Check project bin/ first, then system PATH
FFMPEG_EXE = None
for name in ("ffmpeg.exe", "ffmpeg"):
    candidate = os.path.join(BIN_DIR, name)
    if os.path.isfile(candidate):
        os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")
        FFMPEG_EXE = candidate
        logger.info(f"FFmpeg found: {FFMPEG_EXE}")
        break

if not FFMPEG_EXE:
    FFMPEG_EXE = shutil.which("ffmpeg") or "ffmpeg"
    logger.info(f"FFmpeg from system: {FFMPEG_EXE}")

import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Config
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "downloads")
RESULTS_PER_PAGE = 10
TOTAL_RESULTS = 40

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)


def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USER_ID or ALLOWED_USER_ID.strip() == "":
        return True
    try:
        return user_id == int(ALLOWED_USER_ID.strip())
    except ValueError:
        return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("Sorry, this is a private bot.")
        return

    welcome_text = (
        f"Hi <b>{html.escape(user.first_name)}</b>!\n\n"
        "🎵 <b>Music Downloader Bot</b>\n\n"
        "Send me a song name or artist to search & download MP3s!\n\n"
        "🔹 <b>Example</b>: <code>Cheb Reda Sbabi L'amour</code>\n"
        "🔹 <b>Or paste a YouTube link</b>"
    )
    await update.message.reply_text(welcome_text, parse_mode="HTML")


def get_ydl_opts(custom_opts=None):
    """Returns yt-dlp options configured to bypass YouTube bot detection on cloud servers."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        # Bypass 'Sign in to confirm you're not a bot' on cloud datacenter IPs (Back4App, AWS, etc.)
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "mweb", "web_creator", "tv", "web_embedded"],
            }
        },
    }
    
    cookies_file = os.path.join(SCRIPT_DIR, "cookies.txt")
    if os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
        
    if custom_opts:
        opts.update(custom_opts)
    return opts


async def search_music(query: str, count: int = TOTAL_RESULTS):
    """Search for music using yt-dlp. Returns up to `count` results."""
    ydl_opts = get_ydl_opts({
        "extract_flat": "in_playlist",
    })

    def _search():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(f"ytsearch{count}:{query}", download=False)

    return await asyncio.get_event_loop().run_in_executor(None, _search)


def format_duration(seconds):
    if not seconds:
        return "?:??"
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def build_results_page(entries, page, query):
    """Build the inline keyboard for a specific results page."""
    total = len(entries)
    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    start_idx = page * RESULTS_PER_PAGE
    end_idx = min(start_idx + RESULTS_PER_PAGE, total)
    page_entries = entries[start_idx:end_idx]

    keyboard = []

    # Song buttons
    for idx, entry in enumerate(page_entries, start=start_idx + 1):
        title = entry.get("title", "Unknown Title")
        duration = format_duration(entry.get("duration"))
        video_id = entry.get("id")
        button_label = f"{idx}. {title[:45]} ({duration})"
        keyboard.append(
            [InlineKeyboardButton(button_label, callback_data=f"dl:{video_id}")]
        )

    # Pagination row
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("<<", callback_data=f"page:{page - 1}"))
    nav_buttons.append(
        InlineKeyboardButton(f"{page + 1} / {total_pages}", callback_data="noop")
    )
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(">>", callback_data=f"page:{page + 1}"))
    keyboard.append(nav_buttons)

    # Download All button
    keyboard.append(
        [InlineKeyboardButton("⬇ Download All", callback_data="dlall")]
    )

    text = (
        f"🎵 <b>Search results for</b>: <code>{html.escape(query)}</code>\n"
        f"Select a track to download:"
    )

    return text, InlineKeyboardMarkup(keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("Sorry, this is a private bot.")
        return

    text = update.message.text.strip()
    if not text:
        return

    # Direct URL
    if re.match(r"https?://\S+", text):
        await download_and_send(update.message, text)
        return

    # Search query
    status_msg = await update.message.reply_text(
        f"Searching for <code>{html.escape(text)}</code>...", parse_mode="HTML"
    )

    try:
        results_data = await search_music(text)
        entries = results_data.get("entries", [])

        if not entries:
            await status_msg.edit_text("No results found. Try a different search term.")
            return

        # Store results in user_data for pagination
        context.user_data["results"] = entries
        context.user_data["query"] = text
        context.user_data["page"] = 0

        msg_text, reply_markup = build_results_page(entries, 0, text)
        await status_msg.edit_text(msg_text, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        await status_msg.edit_text("Search failed. Please try again.")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.message.reply_text("Sorry, this is a private bot.")
        return

    data = query.data

    # No-op button (page indicator)
    if data == "noop":
        return

    # Pagination
    if data.startswith("page:"):
        page = int(data.split(":")[1])
        entries = context.user_data.get("results", [])
        search_query = context.user_data.get("query", "")

        if not entries:
            await query.message.edit_text("Session expired. Please search again.")
            return

        context.user_data["page"] = page
        msg_text, reply_markup = build_results_page(entries, page, search_query)
        await query.message.edit_text(msg_text, reply_markup=reply_markup, parse_mode="HTML")
        return

    # Download single track
    if data.startswith("dl:"):
        video_id = data[3:]
        url = f"https://www.youtube.com/watch?v={video_id}"
        await download_and_send(query.message, url)
        return

    # Download All (current page)
    if data == "dlall":
        entries = context.user_data.get("results", [])
        page = context.user_data.get("page", 0)

        if not entries:
            await query.message.reply_text("Session expired. Please search again.")
            return

        start_idx = page * RESULTS_PER_PAGE
        end_idx = min(start_idx + RESULTS_PER_PAGE, len(entries))
        page_entries = entries[start_idx:end_idx]

        await query.message.reply_text(
            f"Downloading {len(page_entries)} tracks from page {page + 1}..."
        )

        for entry in page_entries:
            video_id = entry.get("id")
            if video_id:
                url = f"https://www.youtube.com/watch?v={video_id}"
                await download_and_send(query.message, url)
        return


async def download_and_send(message, url: str):
    """Download audio with yt-dlp, convert with ffmpeg, send to Telegram."""
    status_msg = await message.reply_text("Downloading audio...")

    timestamp = int(asyncio.get_event_loop().time())

    # Step 1: Download raw audio (no postprocessors)
    ydl_opts = get_ydl_opts({
        "format": "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"%(id)s_{timestamp}.%(ext)s"),
        "writethumbnail": True,
    })

    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=True)

    try:
        info = await asyncio.get_event_loop().run_in_executor(None, _download)

        video_id = info.get("id")
        title = info.get("title", "Audio Track")
        artist = info.get("artist") or info.get("uploader") or "Unknown Artist"
        duration = int(info.get("duration") or 0)

        # Find downloaded raw audio file
        raw_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"*{video_id}_{timestamp}.*"))
        audio_extensions = ('.webm', '.m4a', '.opus', '.ogg', '.mp4', '.mp3', '.aac', '.wav', '.flac')
        raw_audio = [f for f in raw_files if os.path.splitext(f)[1].lower() in audio_extensions]

        if not raw_audio:
            await status_msg.edit_text("Download failed - no audio file found.")
            return

        raw_path = raw_audio[0]
        mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_{timestamp}.mp3")

        # Step 2: Convert to MP3 with ffmpeg
        await status_msg.edit_text("Converting to MP3...")

        def _convert():
            cmd = [
                FFMPEG_EXE, "-i", raw_path,
                "-vn", "-ab", "192k", "-ar", "44100", "-y",
                mp3_path
            ]
            return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        convert_result = await asyncio.get_event_loop().run_in_executor(None, _convert)

        if convert_result.returncode != 0 or not os.path.isfile(mp3_path):
            logger.error(f"FFmpeg error: {convert_result.stderr[:500]}")
            await status_msg.edit_text("MP3 conversion failed.")
            return

        # Find thumbnail
        thumb_path = None
        for ext in ("jpg", "png", "webp"):
            thumbs = glob.glob(os.path.join(DOWNLOAD_DIR, f"*{video_id}*.{ext}"))
            if thumbs:
                thumb_path = thumbs[0]
                break

        # Step 3: Upload to Telegram (with increased timeout for slow connections)
        await status_msg.edit_text("Uploading to Telegram...")

        with open(mp3_path, "rb") as audio_file:
            thumb_file = open(thumb_path, "rb") if thumb_path else None
            try:
                await message.reply_audio(
                    audio=audio_file,
                    title=title,
                    performer=artist,
                    duration=duration,
                    thumbnail=thumb_file,
                    caption=f"🎵 <b>{html.escape(title)}</b>\n👤 {html.escape(artist)}",
                    parse_mode="HTML",
                    read_timeout=60,
                    write_timeout=60,
                    connect_timeout=30,
                )
            finally:
                if thumb_file:
                    thumb_file.close()

        await status_msg.delete()

        # Cleanup
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"*{video_id}*")):
            try:
                os.remove(f)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Download error for {url}: {e}", exc_info=True)
        await status_msg.edit_text(
            f"Download failed.\n<code>{html.escape(str(e)[:200])}</code>",
            parse_mode="HTML",
        )


class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Bot is online and running 24/7!</h1></body></html>")

    def log_message(self, format, *args):
        pass


def start_dummy_server(port):
    try:
        server = HTTPServer(("0.0.0.0", port), DummyHandler)
        logger.info(f"Dummy HTTP server running on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start dummy HTTP server: {e}")


def main():
    if not BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN not set in .env file!")
        return

    # Start dummy HTTP server in a background thread for Render & HuggingFace health checks
    port = int(os.getenv("PORT", 7860))
    http_thread = threading.Thread(target=start_dummy_server, args=(port,), daemon=True)
    http_thread.start()

    print(f"[START] Starting bot with token {BOT_TOKEN[:10]}...")
    print(f"[DIR]   Downloads: {DOWNLOAD_DIR}")
    print(f"[FFMPEG] {FFMPEG_EXE}")
    print(f"[HTTP]  Listening on port {port} (for cloud health monitoring)")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("[OK] Bot is online! Send /start to @DownBashaBot")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
