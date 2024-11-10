FROM python:3.13.0-alpine3.20

WORKDIR /opt/sofar2mqtt

COPY requirements.txt sofar2mqtt-v2.py *.json ./

ARG TARGETOS
ARG TARGETARCH

RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} pip install --no-cache-dir -r requirements.txt

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

CMD [ "python", "sofar2mqtt-v2.py" ]

