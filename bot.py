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
SOCIALKIT_ACCESS_KEY = os.getenv("SOCIALKIT_ACCESS_KEY")
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


def setup_youtube_cookies():
    """Load YouTube cookies from YOUTUBE_COOKIES_URL or split environment variables with validation."""
    cookies_file = os.path.join(SCRIPT_DIR, "cookies.txt")
    
    # Always re-create cookies.txt on startup to pick up fresh env vars on each deploy
    if os.path.isfile(cookies_file):
        os.remove(cookies_file)

    # Option 1: Download from a private Gist URL or Paste URL if provided (or if YOUTUBE_COOKIES holds a URL)
    cookies_url = os.getenv("YOUTUBE_COOKIES_URL", "").strip()
    if not cookies_url:
        main_val = os.getenv("YOUTUBE_COOKIES", "").strip()
        if main_val.startswith("http://") or main_val.startswith("https://"):
            cookies_url = main_val

    if cookies_url:
        try:
            import urllib.request
            # Auto-convert standard GitHub Gist link to its raw plain-text URL
            if "gist.github.com" in cookies_url and "/raw" not in cookies_url:
                cookies_url = cookies_url.rstrip("/") + "/raw"
                
            logger.info(f"Downloading YouTube cookies from {cookies_url}...")
            req = urllib.request.Request(cookies_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/plain"})
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read().decode("utf-8", errors="ignore")
            
            # Validate that the downloaded content is plain text cookies, NOT an HTML webpage
            if content.strip().startswith("<") or "<!DOCTYPE" in content or "<html" in content:
                logger.error("Downloaded cookies.txt appears to be an HTML webpage! Discarding.")
                return
            
            with open(cookies_file, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Successfully loaded cookies from URL into cookies.txt ({os.path.getsize(cookies_file)} bytes)")
            return
        except Exception as e:
            logger.error(f"Failed to download cookies from URL: {e}")
            return  # Don't fall through to chunk mode if a URL was provided

    # Option 2: Combine YOUTUBE_COOKIES, YOUTUBE_COOKIES_1, YOUTUBE_COOKIES_2, etc. (bypasses 1023 char limit)
    cookie_chunks = []
    main_cookie = os.getenv("YOUTUBE_COOKIES", "").strip()
    # Skip if main_cookie is a URL (already handled above and failed)
    if main_cookie and not main_cookie.startswith("http"):
        cookie_chunks.append(main_cookie)
    for i in range(1, 10):
        chunk = os.getenv(f"YOUTUBE_COOKIES_{i}", "").strip()
        if chunk:
            cookie_chunks.append(chunk)

    combined_cookies = "\n".join(cookie_chunks)
    if combined_cookies:
        try:
            with open(cookies_file, "w", encoding="utf-8") as f:
                f.write(combined_cookies.replace("\\t", "\t").replace("\\n", "\n"))
            logger.info(f"Successfully saved YOUTUBE_COOKIES (combined) into cookies.txt ({os.path.getsize(cookies_file)} bytes)")
        except Exception as e:
            logger.error(f"Failed to write YOUTUBE_COOKIES to file: {e}")


def get_cookies_status():
    """Return a diagnostic string about the cookies file state."""
    cookies_file = os.path.join(SCRIPT_DIR, "cookies.txt")
    if not os.path.isfile(cookies_file):
        return "❌ No cookies.txt file found"
    size = os.path.getsize(cookies_file)
    if size == 0:
        return "❌ cookies.txt exists but is empty (0 bytes)"
    try:
        with open(cookies_file, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
            line_count = 1 + sum(1 for _ in f)
        if "Netscape" in first_line or first_line.startswith("#") or "\t" in first_line or ".youtube.com" in first_line:
            return f"✅ cookies.txt loaded ({size} bytes, {line_count} lines)"
        else:
            return f"⚠️ cookies.txt exists ({size} bytes) but may be invalid. First line: {first_line[:80]}"
    except Exception as e:
        return f"❌ Error reading cookies.txt: {e}"


def check_pot_server():
    """Check if the PO Token provider HTTP server is running."""
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:4416/", method="GET")
        with urllib.request.urlopen(req, timeout=2):
            return True
    except Exception:
        return False


setup_youtube_cookies()
logger.info(f"Cookie status: {get_cookies_status()}")
logger.info(f"POT server: {'✅ Running on port 4416' if check_pot_server() else '❌ Not detected'}")


def get_ydl_opts(custom_opts=None, player_clients=None, include_cookies=True):
    """Returns yt-dlp options configured to bypass YouTube bot detection on cloud servers."""
    if not player_clients:
        # 2026-optimized: 'default' and 'web' work best with POT tokens on datacenter IPs
        player_clients = ["default", "web", "mweb", "tv_embedded"]

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {
            "youtube": {
                "player_client": player_clients,
            }
        },
    }
    
    cookies_file = os.path.join(SCRIPT_DIR, "cookies.txt")
    if include_cookies and os.path.isfile(cookies_file):
        opts["cookiefile"] = cookies_file
        
    if custom_opts:
        opts.update(custom_opts)
    return opts


async def search_music(query: str, count: int = TOTAL_RESULTS):
    """Search for music using YouTube first (with secret Gist cookies), falling back to clean SoundCloud search."""
    def _search():
        # 1. Try YouTube search first (uses Gist cookies if available)
        try:
            yt_opts = get_ydl_opts({"extract_flat": "in_playlist"}, include_cookies=True)
            with yt_dlp.YoutubeDL(yt_opts) as ydl:
                res = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
                if res and res.get("entries"):
                    logger.info(f"YouTube search returned {len(res['entries'])} results.")
                    return res
        except Exception as e:
            logger.warning(f"YouTube search errored or blocked ({e}), switching to SoundCloud...")

        # 2. Fallback to clean SoundCloud search without YouTube cookie/extractor parameters
        try:
            sc_opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist"}
            with yt_dlp.YoutubeDL(sc_opts) as ydl:
                res = ydl.extract_info(f"scsearch{count}:{query}", download=False)
                if res and res.get("entries"):
                    logger.info(f"SoundCloud search returned {len(res['entries'])} results.")
                    return res
        except Exception as e2:
            logger.error(f"SoundCloud search failed as well: {e2}")
            
        return {"entries": []}

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
    """Build the inline keyboard for a specific results page using entry indices."""
    total = len(entries)
    total_pages = (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE
    start_idx = page * RESULTS_PER_PAGE
    end_idx = min(start_idx + RESULTS_PER_PAGE, total)
    page_entries = entries[start_idx:end_idx]

    keyboard = []

    # Song buttons (using index in entries array for robust URL/ID resolution)
    for idx_offset, entry in enumerate(page_entries):
        real_idx = start_idx + idx_offset
        title = entry.get("title") or "Unknown Title"
        duration = format_duration(entry.get("duration"))
        button_label = f"{real_idx + 1}. {title[:42]} ({duration})"
        keyboard.append(
            [InlineKeyboardButton(button_label, callback_data=f"dl:{real_idx}")]
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


async def parse_spotify_url(url: str) -> str:
    """Extracts song title and artist from a Spotify web page URL."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        html_page = await asyncio.get_event_loop().run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=5).read().decode("utf-8", errors="ignore"))
        title_match = re.search(r'<meta property="og:title" content="([^"]+)"', html_page) or re.search(r'<title>([^<]+)</title>', html_page)
        desc_match = re.search(r'<meta property="og:description" content="([^"]+)"', html_page)
        title = html.unescape(title_match.group(1).split(" | ")[0]) if title_match else ""
        artist = ""
        if desc_match:
            parts = [html.unescape(p.strip()) for p in desc_match.group(1).split("·") if p.strip().lower() != "song"]
            if parts:
                artist = parts[0]
        return f"{title} {artist}".strip()
    except Exception as e:
        logger.error(f"Failed to parse Spotify URL: {e}")
        return ""


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("Sorry, this is a private bot.")
        return

    text = update.message.text.strip()
    if not text:
        return

    # Direct URL (YouTube, SoundCloud, Spotify, etc.)
    if re.match(r"https?://\S+", text):
        await download_and_send(update.message, text)
        return
    else:
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

    # Download single track from array index
    if data.startswith("dl:"):
        idx = int(data[3:])
        entries = context.user_data.get("results", [])
        if idx >= len(entries):
            await query.message.reply_text("Track not found in session. Please search again.")
            return
        entry = entries[idx]
        url = entry.get("url") or entry.get("webpage_url")
        video_id = entry.get("id", "")
        title = entry.get("title", "")
        artist = entry.get("uploader") or entry.get("artist", "")
        fallback_query = f"{title} {artist}".strip()

        if not url or not str(url).startswith("http"):
            if str(video_id).isdigit():
                url = f"https://api.soundcloud.com/tracks/{video_id}"
            else:
                url = f"https://www.youtube.com/watch?v={video_id}"

        await download_and_send(query.message, url, fallback_query=fallback_query)
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
            url = entry.get("url") or entry.get("webpage_url")
            video_id = entry.get("id", "")
            title = entry.get("title", "")
            if not url or not str(url).startswith("http"):
                if str(video_id).isdigit():
                    url = f"https://api.soundcloud.com/tracks/{video_id}"
                else:
                    url = f"https://www.youtube.com/watch?v={video_id}"
            await download_and_send(query.message, url, fallback_query=title)
        return


async def download_via_piped(video_id: str, timestamp: int) -> dict:
    """Download YouTube audio via Piped API instances (bypasses YouTube datacenter IP blocking)."""
    import urllib.request
    import json

    piped_instances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.adminforge.de",
        "https://api.piped.projectsegfau.lt",
        "https://pipedapi.in.projectsegfau.lt",
        "https://pipedapi.leptons.xyz",
        "https://pipedapi.r4fo.com",
        "https://pipedapi.ngn.tf",
        "https://pipedapi.darkness.services",
    ]

    for api_base in piped_instances:
        try:
            api_url = f"{api_base}/streams/{video_id}"
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            title = data.get("title", "Audio Track")
            uploader = data.get("uploader", "Unknown Artist")
            duration = data.get("duration", 0)

            # Pick highest quality audio stream
            audio_streams = data.get("audioStreams", [])
            if not audio_streams:
                logger.warning(f"Piped {api_base}: no audio streams for {video_id}")
                continue

            # Sort by bitrate descending, prefer m4a/mp4 over webm
            audio_streams.sort(key=lambda s: s.get("bitrate", 0), reverse=True)
            best = audio_streams[0]
            stream_url = best.get("url")
            if not stream_url:
                continue

            # Download the audio stream directly
            ext = "m4a" if "m4a" in best.get("mimeType", "") or "mp4" in best.get("mimeType", "") else "webm"
            out_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_{timestamp}.{ext}")

            logger.info(f"Piped {api_base}: downloading {best.get('bitrate', '?')}bps {ext} stream for {video_id}")
            dl_req = urllib.request.Request(stream_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(dl_req, timeout=60) as stream_resp:
                with open(out_path, "wb") as f:
                    while True:
                        chunk = stream_resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)

            if os.path.isfile(out_path) and os.path.getsize(out_path) > 10000:
                # Try to get thumbnail
                thumb_url = data.get("thumbnailUrl", "")
                if thumb_url:
                    try:
                        thumb_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_{timestamp}_thumb.jpg")
                        t_req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(t_req, timeout=10) as t_resp:
                            with open(thumb_path, "wb") as tf:
                                tf.write(t_resp.read())
                    except Exception:
                        pass

                return {
                    "id": video_id,
                    "title": title,
                    "uploader": uploader,
                    "duration": duration,
                    "source": f"piped:{api_base}",
                }

            logger.warning(f"Piped {api_base}: downloaded file too small for {video_id}")
        except Exception as e:
            logger.warning(f"Piped {api_base} failed for {video_id}: {e}")
            continue

    return None


async def download_via_socialkit(url: str, video_id: str, timestamp: int) -> dict:
    """Download audio using SocialKit API (consumes free credits, so used as fallback)."""
    if not SOCIALKIT_ACCESS_KEY:
        return None

    import urllib.request
    import urllib.parse
    import json

    try:
        logger.info(f"SocialKit API: requesting audio stream for {url}...")
        params = urllib.parse.urlencode({
            "access_key": SOCIALKIT_ACCESS_KEY,
            "url": url,
            "format": "m4a"
        })
        api_url = f"https://api.socialkit.dev/v2/youtube/download?{params}"

        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        logger.info(f"SocialKit response: status={data.get('status', 'unknown')}")

        # Extract download URL from typical SocialKit responses
        dl_url = None
        title = "Audio Track"
        uploader = "Unknown Artist"
        duration = 0

        if isinstance(data, dict):
            if data.get("url") and isinstance(data.get("url"), str):
                dl_url = data["url"]
            elif data.get("data") and isinstance(data["data"], dict) and data["data"].get("url"):
                dl_url = data["data"]["url"]
            elif data.get("result") and isinstance(data["result"], dict) and data["result"].get("url"):
                dl_url = data["result"]["url"]

            title = data.get("title") or data.get("data", {}).get("title") or title
            duration = int(data.get("duration") or data.get("data", {}).get("duration") or 0)

        if not dl_url:
            logger.warning(f"SocialKit API did not return a valid audio download url. Response: {data}")
            return None

        out_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_{timestamp}.m4a")
        logger.info(f"SocialKit API: downloading audio from {dl_url[:50]}...")
        dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(dl_req, timeout=60) as stream_resp:
            with open(out_path, "wb") as f:
                while True:
                    chunk = stream_resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)

        if os.path.isfile(out_path) and os.path.getsize(out_path) > 10000:
            return {
                "id": video_id,
                "title": title,
                "uploader": uploader,
                "duration": duration,
                "source": "socialkit",
            }
    except Exception as e:
        logger.error(f"SocialKit API failed for {url}: {e}")

    return None


async def download_via_spotdl(query_or_url: str, timestamp: int) -> dict:
    """Download audio with spotDL (free, embeds ID3 lyrics and artwork from Spotify)."""
    import shutil
    spotdl_exe = shutil.which("spotdl") or "spotdl"

    out_tmpl = os.path.join(DOWNLOAD_DIR, f"spotdl_{timestamp}_{{track-id}}.{{output-ext}}")
    cmd = [
        spotdl_exe,
        query_or_url,
        "--format", "mp3",
        "--output", out_tmpl,
        "--ffmpeg", FFMPEG_EXE,
        "--overwrite", "force",
    ]
    logger.info(f"Running spotdl: {' '.join(cmd)}")
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(f"spotdl failed: {stderr.decode(errors='ignore')}")
            return None

        downloaded = glob.glob(os.path.join(DOWNLOAD_DIR, f"spotdl_{timestamp}_*.mp3"))
        if not downloaded:
            logger.warning("spotdl finished with returncode 0 but no output file found.")
            return None

        file_path = downloaded[0]
        filename = os.path.basename(file_path)
        track_id = filename.split(".")[0]

        return {
            "id": track_id,
            "title": query_or_url if not query_or_url.startswith("http") else "Spotify Track",
            "uploader": "Spotify / spotDL",
            "duration": 0,
            "source": "spotdl",
            "pre_converted_mp3": file_path,
        }
    except Exception as e:
        logger.error(f"spotdl execution error: {e}")
        return None


async def download_and_send(message, url: str, fallback_query: str = None):
    """Download audio with yt-dlp, convert with ffmpeg, send to Telegram."""
    status_msg = await message.reply_text("Downloading audio...")

    timestamp = int(asyncio.get_event_loop().time())

    # Step 1: Download raw audio with fallback client strategies
    def _download(target_url):
        strategies = [
            ["tv_embedded", "web_embedded"],
            ["tv", "music"],
            ["ios", "mweb"],
            ["android", "android_vr"],
            ["web_creator", "web"],
        ]
        last_exception = None
        for strategy in strategies:
            ydl_opts = get_ydl_opts({
                "format": "bestaudio/best",
                "outtmpl": os.path.join(DOWNLOAD_DIR, f"%(id)s_{timestamp}.%(ext)s"),
                "writethumbnail": True,
            }, player_clients=strategy)
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(target_url, download=True)
            except Exception as e:
                last_exception = e
                logger.warning(f"Download attempt failed with strategy {strategy} for {target_url}: {e}")
                continue
        raise last_exception or Exception("All download strategies failed.")

    try:
        info = None
        last_error = "Could not download stream."

        # Attempt 1: For Spotify URLs, use spotDL directly
        if "spotify.com" in str(url):
            logger.info(f"Spotify link detected ({url}). Using spotDL...")
            await status_msg.edit_text("🎵 Downloading Spotify track with spotDL...")
            info = await download_via_spotdl(url, timestamp)

        # Extract YouTube video ID if applicable
        yt_video_id = None
        yt_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", str(url))
        if yt_match:
            yt_video_id = yt_match.group(1)

        # Attempt 2: For YouTube URLs, try Piped API FIRST (datacenter IPs are always blocked by YouTube)
        if not info and yt_video_id:
            logger.info(f"YouTube video detected ({yt_video_id}). Trying Piped API first...")
            await status_msg.edit_text("🔄 Fetching audio stream...")
            info = await download_via_piped(yt_video_id, timestamp)

        # Attempt 3: Direct yt-dlp download (for SoundCloud URLs or if Piped failed)
        if not info and "spotify.com" not in str(url):
            logger.info(f"Trying direct yt-dlp download for {url}...")
            if yt_video_id:
                await status_msg.edit_text("🔄 Trying direct YouTube stream...")
            try:
                info = await asyncio.get_event_loop().run_in_executor(None, _download, url)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Direct yt-dlp download failed for {url}: {e}")

        # Attempt 4: Try spotDL free fallback before consuming paid API credits!
        if not info and fallback_query:
            logger.info(f"Primary methods failed. Trying spotDL fallback for: {fallback_query}...")
            await status_msg.edit_text("⚡ Switching to spotDL audio downloader...")
            info = await download_via_spotdl(fallback_query, timestamp)

        # Attempt 5: Try SocialKit API (if configured in .env and free methods failed)
        if not info and yt_video_id and SOCIALKIT_ACCESS_KEY:
            logger.info(f"Free methods failed. Trying SocialKit API for {url}...")
            await status_msg.edit_text("⚡ Using SocialKit Cloud API...")
            info = await download_via_socialkit(url, yt_video_id, timestamp)

        # Attempt 6: Cross-platform fallback (SoundCloud / YouTube search)
        if not info:
            if not fallback_query and message.text and not message.text.strip().startswith("http"):
                fallback_query = message.text.strip()

            if fallback_query:
                if yt_video_id or "youtube" in str(url) or "spotify" in str(url):
                    logger.info(f"Primary sources restricted. Switching to SoundCloud for: {fallback_query}")
                    await status_msg.edit_text("⚡ Switching to SoundCloud alternative audio...")
                    try:
                        info = await asyncio.get_event_loop().run_in_executor(None, _download, f"scsearch1:{fallback_query}")
                    except Exception as e:
                        logger.warning(f"scsearch1 failed: {e}")
                        clean_query = fallback_query.split("-")[0].strip() if "-" in fallback_query else fallback_query[:30]
                        try:
                            info = await asyncio.get_event_loop().run_in_executor(None, _download, f"scsearch1:{clean_query}")
                        except Exception as e2:
                            last_error = f"SoundCloud search failed: {e2}"
                else:
                    logger.info(f"SoundCloud failed. Trying YouTube search for: {fallback_query}")
                    await status_msg.edit_text("⚡ Switching to YouTube stream...")
                    try:
                        info = await asyncio.get_event_loop().run_in_executor(None, _download, f"ytsearch1:{fallback_query}")
                    except Exception as e:
                        logger.warning(f"ytsearch1 failed: {e}. Trying Piped search...")
                        try:
                            search_opts = get_ydl_opts({"extract_flat": "in_playlist"}, include_cookies=True)
                            def _yt_search():
                                with yt_dlp.YoutubeDL(search_opts) as ydl:
                                    return ydl.extract_info(f"ytsearch1:{fallback_query}", download=False)
                            search_res = await asyncio.get_event_loop().run_in_executor(None, _yt_search)
                            if search_res and search_res.get("entries"):
                                found_id = search_res["entries"][0].get("id")
                                if found_id:
                                    info = await download_via_piped(found_id, timestamp)
                        except Exception as e2:
                            last_error = f"YouTube fallback failed: {e2}"

        # Unpack playlist / search entry if needed
        if info and isinstance(info, dict) and info.get("entries"):
            info = next((item for item in info["entries"] if item is not None), None)

        # Final check: Ensure we actually obtained track info before extracting attributes
        if not info or not isinstance(info, dict):
            raise Exception(f"Stream unavailable: {last_error}")

        video_id = info.get("id")
        title = info.get("title", "Audio Track")
        artist = info.get("artist") or info.get("uploader") or "Unknown Artist"
        duration = int(info.get("duration") or 0)

        mp3_path = os.path.join(DOWNLOAD_DIR, f"{video_id}_{timestamp}.mp3")

        # Check if file is already a pre-converted MP3 from spotDL
        if info.get("pre_converted_mp3") and os.path.isfile(info["pre_converted_mp3"]):
            mp3_path = info["pre_converted_mp3"]
            logger.info(f"Using pre-converted MP3 from spotDL: {mp3_path}")
        else:
            # Find downloaded raw audio file
            raw_files = glob.glob(os.path.join(DOWNLOAD_DIR, f"*{video_id}_{timestamp}.*"))
            audio_extensions = ('.webm', '.m4a', '.opus', '.ogg', '.mp4', '.mp3', '.aac', '.wav', '.flac')
            raw_audio = [f for f in raw_files if os.path.splitext(f)[1].lower() in audio_extensions]

            if not raw_audio:
                await status_msg.edit_text("Download failed - no audio file found.")
                return

            raw_path = raw_audio[0]
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


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot diagnostics: cookie status, yt-dlp version, ffmpeg."""
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text("Sorry, this is a private bot.")
        return

    cookie_status = get_cookies_status()
    pot_status = "✅ Running on port 4416" if check_pot_server() else "❌ Not detected"
    try:
        ytdlp_version = yt_dlp.version.__version__
    except Exception:
        ytdlp_version = "unknown"

    status_text = (
        "🔧 <b>Bot Status</b>\n\n"
        f"🍪 <b>Cookies:</b> {cookie_status}\n"
        f"🔑 <b>POT Server:</b> {pot_status}\n"
        f"📦 <b>yt-dlp:</b> {ytdlp_version}\n"
        f"🎬 <b>FFmpeg:</b> {FFMPEG_EXE}\n"
        f"📂 <b>Downloads dir:</b> {DOWNLOAD_DIR}\n"
    )
    await update.message.reply_text(status_text, parse_mode="HTML")


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
    print(f"[COOKIE] {get_cookies_status()}")
    print(f"[POT]   {'✅ Running on port 4416' if check_pot_server() else '❌ Not detected'}")
    print(f"[HTTP]  Listening on port {port} (for cloud health monitoring)")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("[OK] Bot is online! Send /start to @DownBashaBot")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
