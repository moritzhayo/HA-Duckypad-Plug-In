#!/usr/bin/with-contenv bashio

set -e

bashio::log.info "Starting HA DuckyPad add-on"
exec python3 /app.py
