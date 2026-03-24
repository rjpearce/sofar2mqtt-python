FROM python:3.14-alpine3.23

WORKDIR /opt/sofar2mqtt

COPY pyproject.toml ./

RUN pip install --no-cache-dir .

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

COPY config/*.json ./

CMD ["sofar2mqtt"]