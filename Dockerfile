FROM python:3.12-slim

# Install ffmpeg and curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install ALL Python dependencies in a single layer (no caching issues)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -U yt-dlp && \
    pip install --no-cache-dir bgutil-ytdlp-pot-provider || echo "POT provider install failed, continuing without it"

# Copy bot code and entrypoint
COPY bot.py .
COPY entrypoint.sh .
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Expose port for cloud health monitoring (Back4App / Render)
ENV PORT=7860
EXPOSE 7860

# Use entrypoint script to start POT server + bot
CMD ["./entrypoint.sh"]
