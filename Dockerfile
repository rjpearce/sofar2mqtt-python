FROM python:3.14-slim

WORKDIR /opt/sofar2mqtt

# Upgrade pip and install system dependencies
RUN pip install --upgrade pip && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml README.md ./

# Install project dependencies (without dev extras which require Rust toolchain on ARM)
RUN pip install --no-cache-dir .

# Copy remaining project files
COPY sofar2mqtt/ ./sofar2mqtt/
COPY config/*.json ./

ENV CONFIG_FILE=sofar-hyd-ep.json \
    DAEMON=True \
    LOG_LEVEL=INFO \
    MQTT_HOST= \
    MQTT_PASSWORD= \
    MQTT_PORT=1883 \
    MQTT_TOPIC=sofar/ \
    MQTT_USERNAME= \
    MQTT_WRITE_TOPIC=sofar/rw \
    REFRESH_INTERVAL=1 \
    RETRY_ATTEMPT=2 \
    RETRY_DELAY=0.1 \
    TTY_DEVICE= \
    WRITE_RETRY_ATTEMPTS=5 \
    WRITE_RETRY_DELAY=5

CMD ["sofar2mqtt"]