FROM python:3.13.0-alpine3.20

WORKDIR /opt/sofar2mqtt

COPY requirements.txt sofar2mqtt-v2.py *.json ./

ARG TARGETOS
ARG TARGETARCH

RUN GOOS=${TARGETOS} GOARCH=${TARGETARCH} pip install --no-cache-dir -r requirements.txt

ENV CONFIG_FILE=sofar-hyd-ep.json \
    DAEMON=True

CMD [ "python", "sofar2mqtt-v2.py" ]

