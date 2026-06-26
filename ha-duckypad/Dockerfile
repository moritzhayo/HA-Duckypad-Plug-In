FROM ghcr.io/home-assistant/base:3.22

ARG BUILD_VERSION=0.2.0
ARG BUILD_ARCH=amd64

LABEL \
  io.hass.name="HA DuckyPad" \
  io.hass.description="Trigger Home Assistant services from DuckyPad Pro USB key events." \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache \
    gcc \
    linux-headers \
    musl-dev \
    py3-pip \
    python3 \
    python3-dev \
  && pip3 install --break-system-packages --no-cache-dir \
    evdev==1.7.1 \
    requests==2.32.3 \
  && apk del \
    gcc \
    linux-headers \
    musl-dev \
    python3-dev

COPY app.py /app.py
COPY run.sh /run.sh

RUN chmod a+x /run.sh

CMD ["/run.sh"]
