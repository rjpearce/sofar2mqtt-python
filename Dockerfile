FROM python:3.14-slim

WORKDIR /opt/sofar2mqtt

# Upgrade pip and install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip

# Copy project files
COPY pyproject.toml README.md ./

# Install project in editable mode to avoid path issues
RUN pip install --no-cache-dir -e .

# Copy remaining project files (excluding __pycache__ and .pyc files)
COPY sofar2mqtt/ ./sofar2mqtt/
COPY config/*.json ./

# Create a non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /opt/sofar2mqtt

USER appuser

ENV CONFIG_FILE= \
    LOG_LEVEL=INFO \
    MQTT_HOST=localhost \
    MQTT_PASSWORD= \
    MQTT_PORT=1883 \
    MQTT_TOPIC=sofar/ \
    MQTT_USERNAME= \
    MQTT_WRITE_TOPIC=sofar/rw \
    TTY_DEVICE=/dev/ttyUSB0 \
    REFRESH_INTERVAL=1
CMD ["sofar2mqtt"]