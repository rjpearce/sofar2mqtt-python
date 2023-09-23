FROM python:3.9.18-slim-bullseye@sha256:25a976dc387d01af6cb8c419a03e4b553d88ac5152d250920c94553e24cad3c7

WORKDIR /opt/sofar2mqtt

COPY requirements.txt sofar2mqtt-v2.py *.json ./

RUN pip install --no-cache-dir -r requirements.txt

ENV CONFIG_FILE=sofar-hyd-ep.json \
    DAEMON=True \
    LOG_LEVEL=INFO \
    MQTT_HOST= \
    MQTT_PASSWORD= \
    MQTT_PORT=1883 \
    MQTT_TOPIC=sofar/ \
    MQTT_USERNAME= \
    MQTT_WRITE_TOPIC=sofar/rw \
    REFRESH_INTERVAL= \
    RETRY_ATTEMPT=2 \
    RETRY_DELAY=0.1 \
    TTY_DEVICE= \
    WRITE_RETRY_ATTEMPTS=2 \
    WRITE_RETRY_DELAY=2 

CMD [ "python", "sofar2mqtt-v2.py" ]

