#!/usr/bin/with-contenv bashio

set -e

bashio::log.info "Starting HA DuckyPad add-on"
python3 /easy_actions.py
exec python3 /app_combo.py
