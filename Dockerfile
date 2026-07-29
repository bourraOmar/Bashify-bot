FROM python:3.12-slim

# Install ffmpeg, curl, and unzip for Deno
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl unzip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Deno (JavaScript runtime required by yt-dlp for YouTube signature handling)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

# Set working directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install yt-dlp nightly (latest patches for YouTube bot detection) + POT provider plugin
RUN pip install --no-cache-dir -U "yt-dlp[default]" bgutil-ytdlp-pot-provider

# Copy bot code and entrypoint
COPY bot.py .
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Expose port for cloud health monitoring (Back4App / Render)
ENV PORT=7860
EXPOSE 7860

# Use entrypoint script to start POT server + bot
CMD ["./entrypoint.sh"]
