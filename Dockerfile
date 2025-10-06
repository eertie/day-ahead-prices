FROM python:3.12-slim

# Set workdir
WORKDIR /app

# System deps (optional but useful for SSL/timezones)
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends ca-certificates tzdata && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency list and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY ha_entsoe.py /app/ha_entsoe.py
COPY api_server.py /app/api_server.py

# Create cache dir (can be overridden by env CACHE_DIR)
RUN mkdir -p /app/cache

# Expose FastAPI port
EXPOSE 8000

# By default, uvicorn will read .env via python-dotenv in code
# but we also pass --env-file as a convenience local override if mounted
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]