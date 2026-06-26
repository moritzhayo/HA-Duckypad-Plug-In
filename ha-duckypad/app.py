#!/usr/bin/env python3

import json
import logging
import os
import stat
import time
from pathlib import Path
from typing import Any

import requests
from evdev import InputDevice, categorize, ecodes


CONFIG_PATH = Path("/data/options.json")
DEFAULT_DEVICE_PATH = (
    "/dev/input/by-id/usb-dekuNukem_duckyPad_Pro_DP24_A1E7C3D4-event-kbd"
)
DEFAULT_OPTIONS = {
    "device_path": DEFAULT_DEVICE_PATH,
    "debounce_ms": 500,
    "hidraw_path": "/dev/hidraw0",
    "enable_hid_debug": False,
    "button_mappings": [
        {
            "key": "KEY_F13",
            "service": "switch.toggle",
            "entity_id": "switch.elegoo",
        },
        {
            "key": "KEY_F14",
            "service": "switch.toggle",
            "entity_id": "switch.voron",
        },
    ],
}
RECONNECT_DELAY_SECONDS = 3
REQUEST_TIMEOUT_SECONDS = 10
KEY_DOWN = 1
IGNORED_KEYS = {
    "KEY_LEFTALT",
    "KEY_LEFTCTRL",
    "KEY_LEFTMETA",
    "KEY_LEFTSHIFT",
    "KEY_RIGHTALT",
    "KEY_RIGHTCTRL",
    "KEY_RIGHTMETA",
    "KEY_RIGHTSHIFT",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [ha-duckypad] %(message)s",
)
LOGGER = logging.getLogger("ha-duckypad")


def load_options() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        LOGGER.warning(
            "Options file %s not found, using built-in defaults", CONFIG_PATH
        )
        return DEFAULT_OPTIONS

    with CONFIG_PATH.open("r", encoding="utf-8") as options_file:
        options = json.load(options_file)

    return {
        "device_path": options.get("device_path") or DEFAULT_DEVICE_PATH,
        "debounce_ms": int(options.get("debounce_ms", 500)),
        "hidraw_path": options.get("hidraw_path") or "",
        "enable_hid_debug": bool(options.get("enable_hid_debug", False)),
        "button_mappings": options.get("button_mappings") or [],
    }


def read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as error:
        LOGGER.debug("Could not read %s: %s", path, error)
        return None


def log_hidraw_diagnostics(hidraw_path: str, enabled: bool) -> None:
    if not enabled:
        LOGGER.info("HID debug is disabled")
        return

    if not hidraw_path:
        LOGGER.warning("HID debug is enabled, but no hidraw_path is configured")
        return

    path = Path(hidraw_path)
    LOGGER.info("HID debug enabled for %s", path)

    if not path.exists():
        LOGGER.warning("HID raw device does not exist: %s", path)
        return

    try:
        device_stat = path.stat()
    except OSError as error:
        LOGGER.warning("Could not stat HID raw device %s: %s", path, error)
        return

    mode = stat.S_IMODE(device_stat.st_mode)
    LOGGER.info(
        "HID raw device stat: mode=%s uid=%s gid=%s rdev=%s",
        oct(mode),
        device_stat.st_uid,
        device_stat.st_gid,
        device_stat.st_rdev,
    )

    sysfs_dir = Path("/sys/class/hidraw") / path.name / "device"
    uevent = read_text_file(sysfs_dir / "uevent")
    if uevent:
        LOGGER.info("HID sysfs uevent for %s:\n%s", path.name, uevent)
    else:
        LOGGER.warning("No HID sysfs uevent found for %s at %s", path.name, sysfs_dir)

    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    except OSError as error:
        LOGGER.warning("Could not open HID raw device %s read-only: %s", path, error)
        return

    try:
        LOGGER.info("Opened HID raw device %s read-only successfully", path)
    finally:
        os.close(fd)


def normalize_keycode(keycode: str | list[str]) -> str:
    if isinstance(keycode, list):
        return keycode[0]
    return keycode


def build_mapping_lookup(mappings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}

    for mapping in mappings:
        key = str(mapping.get("key", "")).strip()
        service = str(mapping.get("service", "")).strip()

        if not key or not service:
            LOGGER.warning("Ignoring incomplete mapping: %s", mapping)
            continue

        lookup[key.upper()] = mapping

    LOGGER.info("Loaded %d button mapping(s)", len(lookup))
    return lookup


def get_auth_headers() -> dict[str, str] | None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        LOGGER.error(
            "SUPERVISOR_TOKEN is missing. Key events will be logged, "
            "but Home Assistant service calls are disabled."
        )
        return None

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def get_api_base_url() -> str:
    return os.environ.get("HA_API_BASE_URL", "http://supervisor/core/api").rstrip("/")


def parse_service(service: str) -> tuple[str, str]:
    if "." not in service:
        raise ValueError(f"Service must be in domain.service format: {service}")

    domain, service_name = service.split(".", 1)
    if not domain or not service_name:
        raise ValueError(f"Service must be in domain.service format: {service}")

    return domain, service_name


def call_home_assistant_service(
    mapping: dict[str, Any],
    headers: dict[str, str] | None,
    api_base_url: str,
) -> None:
    service = str(mapping["service"]).strip()

    try:
        domain, service_name = parse_service(service)
    except ValueError as error:
        LOGGER.error("%s", error)
        return

    if headers is None:
        LOGGER.warning("Skipping %s because Home Assistant API auth is unavailable", service)
        return

    data: dict[str, Any] = {}
    entity_id = str(mapping.get("entity_id", "")).strip()
    if entity_id:
        data["entity_id"] = entity_id

    url = f"{api_base_url}/services/{domain}/{service_name}"
    LOGGER.info("Calling Home Assistant service %s with data %s", service, data)

    try:
        response = requests.post(
            url,
            headers=headers,
            json=data,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as error:
        LOGGER.error("Service call failed for %s: %s", service, error)
        return

    LOGGER.info("Service call succeeded for %s with status %s", service, response.status_code)


def wait_for_device(device_path: str) -> None:
    while not Path(device_path).exists():
        LOGGER.warning(
            "Input device not found at %s. Retrying in %s second(s)",
            device_path,
            RECONNECT_DELAY_SECONDS,
        )
        time.sleep(RECONNECT_DELAY_SECONDS)


def read_device_events(
    device_path: str,
    mappings: dict[str, dict[str, Any]],
    headers: dict[str, str] | None,
    api_base_url: str,
    debounce_seconds: float,
) -> None:
    wait_for_device(device_path)
    device = InputDevice(device_path)
    LOGGER.info("Connected to input device: %s (%s)", device.name, device.path)
    last_triggered_at: dict[str, float] = {}

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY:
                continue

            key_event = categorize(event)
            key_name = normalize_keycode(key_event.keycode)
            key_value = event.value
            state_name = {
                0: "key_up",
                1: "key_down",
                2: "key_hold",
            }.get(key_value, f"value_{key_value}")

            LOGGER.info(
                "Received key event: name=%s code=%s state=%s value=%s",
                key_name,
                event.code,
                state_name,
                key_value,
            )

            if key_name.upper() in IGNORED_KEYS:
                continue

            if key_value != KEY_DOWN:
                continue

            mapping = mappings.get(key_name.upper())
            if not mapping:
                LOGGER.info("No mapping configured for %s", key_name)
                continue

            now = time.monotonic()
            previous_triggered_at = last_triggered_at.get(key_name.upper(), 0)
            if debounce_seconds > 0 and now - previous_triggered_at < debounce_seconds:
                LOGGER.info("Ignoring %s because it is inside the debounce window", key_name)
                continue

            last_triggered_at[key_name.upper()] = now
            call_home_assistant_service(mapping, headers, api_base_url)
    finally:
        device.close()


def main() -> None:
    options = load_options()
    device_path = str(options["device_path"])
    debounce_seconds = max(0, int(options.get("debounce_ms", 500))) / 1000
    hidraw_path = str(options.get("hidraw_path", ""))
    enable_hid_debug = bool(options.get("enable_hid_debug", False))
    mappings = build_mapping_lookup(options["button_mappings"])
    headers = get_auth_headers()
    api_base_url = get_api_base_url()

    LOGGER.info("Using input device path: %s", device_path)
    LOGGER.info("Using Home Assistant API base URL: %s", api_base_url)
    LOGGER.info("Using debounce window: %.3f second(s)", debounce_seconds)
    log_hidraw_diagnostics(hidraw_path, enable_hid_debug)

    while True:
        try:
            read_device_events(
                device_path,
                mappings,
                headers,
                api_base_url,
                debounce_seconds,
            )
        except KeyboardInterrupt:
            LOGGER.info("Stopping HA DuckyPad add-on")
            raise
        except OSError as error:
            LOGGER.warning(
                "Input device disconnected or unavailable: %s. Reconnecting in %s second(s)",
                error,
                RECONNECT_DELAY_SECONDS,
            )
            time.sleep(RECONNECT_DELAY_SECONDS)
        except Exception:
            LOGGER.exception(
                "Unexpected error while reading DuckyPad events. "
                "Restarting reader in %s second(s)",
                RECONNECT_DELAY_SECONDS,
            )
            time.sleep(RECONNECT_DELAY_SECONDS)


if __name__ == "__main__":
    main()
