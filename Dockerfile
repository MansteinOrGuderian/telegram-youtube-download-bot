FROM python:3.12-slim

# ffmpeg is required by yt-dlp for audio extraction and conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY app/         ./app/
COPY yt_download/ ./yt_download/
COPY config.py    .
COPY logger.py    .

# Runtime directories (tmp uses system /tmp via Python's tempfile module)
RUN mkdir -p /app/logs

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "app"]
