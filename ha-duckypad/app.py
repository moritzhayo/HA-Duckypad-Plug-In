#!/usr/bin/env python3

import json
import logging
import os
import select
import stat
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import websocket
from evdev import InputDevice, categorize, ecodes


CONFIG_PATH = Path("/data/options.json")
DEFAULT_DEVICE_PATH = (
    "/dev/input/by-id/usb-dekuNukem_duckyPad_Pro_DP24_A1E7C3D4-event-kbd"
)
DEFAULT_HIDRAW_PATH = "/dev/hidraw0"
DEFAULT_HA_EVENT_COMMAND_TYPE = "ha_duckypad_hid_command"
DEFAULT_OPTIONS = {
    "device_path": DEFAULT_DEVICE_PATH,
    "debounce_ms": 500,
    "hidraw_path": DEFAULT_HIDRAW_PATH,
    "enable_hid_debug": False,
    "enable_hid_commands": False,
    "enable_ha_event_commands": False,
    "ha_event_command_type": DEFAULT_HA_EVENT_COMMAND_TYPE,
    "enable_entity_state_events": False,
    "hid_commands_on_start": [],
    "entity_state_sync_interval": 0,
    "entity_state_mappings": [],
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
HA_EVENT_RECONNECT_DELAY_SECONDS = 5
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

HID_REPORT_SIZE = 64
HID_RESPONSE_TIMEOUT_SECONDS = 1.0
HID_USAGE_ID_TO_DUCKYPAD = 0x05
HID_USAGE_ID_FROM_DUCKYPAD = 0x04
HID_COMMAND_CODES = {
    "get_info": 0x00,
    "goto_profile_number": 0x01,
    "previous_profile": 0x02,
    "prev_profile": 0x02,
    "next_profile": 0x03,
    "set_rgb": 0x04,
    "sleep": 0x15,
    "wake": 0x16,
    "wake_up": 0x16,
    "goto_profile_name": 0x17,
    "dump_gv": 0x18,
    "write_gv": 0x19,
    "set_rtc": 0x1A,
}
HID_STATUS_NAMES = {
    0: "success",
    1: "error",
    2: "busy",
    4: "no_profile",
    5: "invalid_arg",
    6: "unknown_cmd",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [ha-duckypad] %(message)s",
)
LOGGER = logging.getLogger("ha-duckypad")
HID_LOCK = threading.Lock()


def as_optional_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def load_options() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        LOGGER.warning(
            "Options file %s not found, using built-in defaults", CONFIG_PATH
        )
        return DEFAULT_OPTIONS

    with CONFIG_PATH.open("r", encoding="utf-8") as options_file:
        options = json.load(options_file)

    return {
        "device_path": as_optional_string(options.get("device_path"))
        or DEFAULT_DEVICE_PATH,
        "debounce_ms": int(options.get("debounce_ms", 500)),
        "hidraw_path": as_optional_string(options.get("hidraw_path"))
        or DEFAULT_HIDRAW_PATH,
        "enable_hid_debug": bool(options.get("enable_hid_debug", False)),
        "enable_hid_commands": bool(options.get("enable_hid_commands", False)),
        "enable_ha_event_commands": bool(
            options.get("enable_ha_event_commands", False)
        ),
        "ha_event_command_type": as_optional_string(
            options.get("ha_event_command_type")
        )
        or DEFAULT_HA_EVENT_COMMAND_TYPE,
        "enable_entity_state_events": bool(
            options.get("enable_entity_state_events", False)
        ),
        "hid_commands_on_start": options.get("hid_commands_on_start") or [],
        "entity_state_sync_interval": int(
            options.get("entity_state_sync_interval", 0)
        ),
        "entity_state_mappings": options.get("entity_state_mappings") or [],
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


def normalize_hid_command(command: str) -> str:
    return command.strip().lower().replace("-", "_")


def build_mapping_lookup(mappings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}

    for mapping in mappings:
        key = as_optional_string(mapping.get("key"))
        service = as_optional_string(mapping.get("service"))
        hid_command = as_optional_string(mapping.get("hid_command"))

        if not key or (not service and not hid_command):
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


def get_home_assistant_websocket_url(api_base_url: str) -> str:
    configured_url = as_optional_string(os.environ.get("HA_WEBSOCKET_URL"))
    if configured_url:
        return configured_url

    if api_base_url.endswith("/core/api"):
        http_url = api_base_url[: -len("/api")] + "/websocket"
    elif api_base_url.endswith("/api"):
        http_url = api_base_url[: -len("/api")] + "/api/websocket"
    else:
        http_url = api_base_url.rstrip("/") + "/websocket"

    if http_url.startswith("https://"):
        return "wss://" + http_url[len("https://") :]
    if http_url.startswith("http://"):
        return "ws://" + http_url[len("http://") :]
    return http_url


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
    service = as_optional_string(mapping.get("service"))
    if not service:
        return

    try:
        domain, service_name = parse_service(service)
    except ValueError as error:
        LOGGER.error("%s", error)
        return

    if headers is None:
        LOGGER.warning("Skipping %s because Home Assistant API auth is unavailable", service)
        return

    data: dict[str, Any] = {}
    entity_id = as_optional_string(mapping.get("entity_id"))
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


def get_home_assistant_entity_state(
    entity_id: str,
    headers: dict[str, str] | None,
    api_base_url: str,
) -> dict[str, Any] | None:
    if headers is None:
        LOGGER.warning("Skipping state read for %s because API auth is unavailable", entity_id)
        return None

    url = f"{api_base_url}/states/{entity_id}"

    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as error:
        LOGGER.error("State read failed for %s: %s", entity_id, error)
    except ValueError as error:
        LOGGER.error("State response for %s was not valid JSON: %s", entity_id, error)

    return None


def config_int(
    config: dict[str, Any],
    key: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be an integer") from error

    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} must be <= {maximum}")

    return value


def get_mapping_source_value(mapping: dict[str, Any], state_data: dict[str, Any]) -> Any:
    attribute = as_optional_string(mapping.get("attribute"))
    if not attribute:
        return state_data.get("state")

    attributes = state_data.get("attributes") or {}
    if not isinstance(attributes, dict):
        return None

    return attributes.get(attribute)


def list_from_config(value: Any, fallback: list[str]) -> list[str]:
    if value is None:
        return fallback
    if isinstance(value, list):
        return [as_optional_string(item).lower() for item in value if as_optional_string(item)]
    text = as_optional_string(value)
    if not text:
        return fallback
    return [item.strip().lower() for item in text.split(",") if item.strip()]


def map_state_value_to_gv(mapping: dict[str, Any], raw_value: Any) -> int | None:
    state_type = as_optional_string(mapping.get("state_type")).lower() or "auto"
    value_text = as_optional_string(raw_value)
    value_lower = value_text.lower()

    unavailable_values = {"unknown", "unavailable", "none", ""}
    if value_lower in unavailable_values:
        if "default_value" in mapping:
            return config_int(mapping, "default_value", 0, -(2**31), 2**31 - 1)
        return None

    on_states = list_from_config(
        mapping.get("on_states"),
        ["on", "open", "home", "playing", "heat", "cool", "true", "1"],
    )
    off_states = list_from_config(
        mapping.get("off_states"),
        ["off", "closed", "not_home", "idle", "standby", "false", "0"],
    )

    if state_type in {"auto", "bool", "boolean"}:
        if value_lower in on_states:
            return config_int(mapping, "on_value", 1, -(2**31), 2**31 - 1)
        if value_lower in off_states:
            return config_int(mapping, "off_value", 0, -(2**31), 2**31 - 1)
        if state_type in {"bool", "boolean"}:
            if "default_value" in mapping:
                return config_int(mapping, "default_value", 0, -(2**31), 2**31 - 1)
            return None

    if state_type in {"auto", "number", "numeric"}:
        try:
            return round(float(value_text))
        except (TypeError, ValueError):
            if "default_value" in mapping:
                return config_int(mapping, "default_value", 0, -(2**31), 2**31 - 1)
            return None

    return None


def build_hid_packet(config: dict[str, Any]) -> tuple[str, bytes]:
    command = normalize_hid_command(as_optional_string(config.get("hid_command")))
    if not command:
        raise ValueError("hid_command is required")

    command_code = HID_COMMAND_CODES.get(command)
    if command_code is None:
        raise ValueError(f"Unknown HID command: {command}")

    packet = bytearray(HID_REPORT_SIZE)
    packet[0] = HID_USAGE_ID_TO_DUCKYPAD
    packet[1] = 0
    packet[2] = command_code

    if command == "goto_profile_number":
        packet[3] = config_int(config, "profile_number", 1, 1, 255)
    elif command == "goto_profile_name":
        profile_name = as_optional_string(config.get("profile_name"))
        if not profile_name:
            raise ValueError("profile_name is required for goto_profile_name")
        encoded = profile_name.encode("ascii")
        if len(encoded) > HID_REPORT_SIZE - 4:
            raise ValueError("profile_name is too long for one HID packet")
        packet[3 : 3 + len(encoded)] = encoded
    elif command == "set_rgb":
        packet[3] = config_int(config, "led_index", 0, 0, 19)
        packet[4] = config_int(config, "red", 0, 0, 255)
        packet[5] = config_int(config, "green", 0, 0, 255)
        packet[6] = config_int(config, "blue", 0, 0, 255)
    elif command == "dump_gv":
        packet[3] = config_int(config, "gv_index", 0, 0, 31)
    elif command == "write_gv":
        gv_index = config_int(config, "gv_index", 0, 0, 31)
        gv_value = config_int(config, "gv_value", 0, -(2**31), 2**31 - 1)
        packet[3] = 0x80 | gv_index
        packet[4:8] = gv_value.to_bytes(4, "little", signed=True)
    elif command == "set_rtc":
        now = datetime.now().astimezone()
        utc_offset = now.utcoffset()
        offset_minutes = int(utc_offset.total_seconds() // 60) if utc_offset else 0
        packet[3:7] = int(now.timestamp()).to_bytes(4, "little", signed=False)
        packet[7:9] = offset_minutes.to_bytes(2, "little", signed=True)

    return command, bytes(packet)


def read_hid_response(fd: int) -> bytes | None:
    deadline = time.monotonic() + HID_RESPONSE_TIMEOUT_SECONDS

    while time.monotonic() < deadline:
        remaining = max(0, deadline - time.monotonic())
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            return None

        try:
            response = os.read(fd, HID_REPORT_SIZE)
        except BlockingIOError:
            continue

        if response:
            return response

    return None


def send_hid_packet(hidraw_path: str, packet: bytes) -> bytes | None:
    path = Path(hidraw_path)
    if not path.exists():
        raise OSError(f"HID raw device does not exist: {path}")

    fd = os.open(path, os.O_RDWR | getattr(os, "O_NONBLOCK", 0))
    try:
        written = os.write(fd, packet)
        if written != len(packet):
            raise OSError(f"Short HID write: wrote {written} of {len(packet)} bytes")
        return read_hid_response(fd)
    finally:
        os.close(fd)


def parse_hid_response(response: bytes) -> tuple[int | None, int, bytes]:
    if len(response) >= 3 and response[0] == HID_USAGE_ID_FROM_DUCKYPAD:
        return response[0], response[2], response[3:]
    if len(response) >= 2:
        return None, response[1], response[2:]
    raise ValueError(f"HID response is too short: {response!r}")


def log_get_info_response(payload: bytes) -> None:
    if len(payload) < 17:
        LOGGER.warning("get_info response payload is too short: %s", list(payload))
        return

    version = f"{payload[0]}.{payload[1]}.{payload[2]}"
    hardware_revision = payload[3]
    serial_number = int.from_bytes(payload[4:8], "little", signed=False)
    profile_number = payload[8]
    is_sleeping = bool(payload[9])
    is_rtc_valid = bool(payload[10])
    utc_offset = int.from_bytes(payload[11:13], "little", signed=True)
    unix_timestamp = int.from_bytes(payload[13:17], "little", signed=False)

    LOGGER.info(
        "DuckyPad info: firmware=%s hardware_revision=%s serial=%s "
        "profile=%s sleeping=%s rtc_valid=%s utc_offset_minutes=%s unix_time=%s",
        version,
        hardware_revision,
        serial_number,
        profile_number,
        is_sleeping,
        is_rtc_valid,
        utc_offset,
        unix_timestamp,
    )


def log_dump_gv_response(start_index: int, payload: bytes) -> None:
    values: list[str] = []
    for offset in range(0, min(len(payload), 60), 4):
        chunk = payload[offset : offset + 4]
        if len(chunk) < 4:
            break
        index = start_index + offset // 4
        if index > 31:
            break
        value = int.from_bytes(chunk, "little", signed=True)
        values.append(f"_GV{index}={value}")

    LOGGER.info("DuckyPad persistent global variables: %s", ", ".join(values))


def run_configured_hid_command(
    config: dict[str, Any],
    hidraw_path: str,
    enabled: bool,
    source: str,
) -> None:
    command = normalize_hid_command(as_optional_string(config.get("hid_command")))
    if not command:
        return

    if not enabled:
        LOGGER.warning(
            "Skipping HID command %s from %s because enable_hid_commands is false",
            command,
            source,
        )
        return

    if not hidraw_path:
        LOGGER.warning("Skipping HID command %s because hidraw_path is empty", command)
        return

    try:
        command, packet = build_hid_packet(config)
        LOGGER.info("Sending DuckyPad HID command %s from %s", command, source)
        with HID_LOCK:
            response = send_hid_packet(hidraw_path, packet)
    except (OSError, ValueError) as error:
        LOGGER.error("HID command %s failed before response: %s", command, error)
        return

    if response is None:
        LOGGER.warning("HID command %s sent, but no response was received", command)
        return

    try:
        report_id, status, payload = parse_hid_response(response)
    except ValueError as error:
        LOGGER.error("Could not parse HID response for %s: %s", command, error)
        return

    status_name = HID_STATUS_NAMES.get(status, f"status_{status}")
    log_level = logging.INFO if status == 0 else logging.WARNING
    LOGGER.log(
        log_level,
        "HID command %s response: report_id=%s status=%s (%s)",
        command,
        report_id,
        status,
        status_name,
    )

    if status != 0:
        return

    if command == "get_info":
        log_get_info_response(payload)
    elif command == "dump_gv":
        start_index = config_int(config, "gv_index", 0, 0, 31)
        log_dump_gv_response(start_index, payload)


def run_startup_hid_commands(
    commands: list[Any],
    hidraw_path: str,
    enabled: bool,
) -> None:
    if not isinstance(commands, list):
        LOGGER.warning("Ignoring hid_commands_on_start because it is not a list")
        return

    for index, command_config in enumerate(commands, start=1):
        if not isinstance(command_config, dict):
            LOGGER.warning("Ignoring invalid startup HID command: %s", command_config)
            continue
        run_configured_hid_command(
            command_config,
            hidraw_path,
            enabled,
            f"startup command #{index}",
        )


def sync_entity_state_mapping_with_state_data(
    mapping: dict[str, Any],
    state_data: dict[str, Any],
    entity_id: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    if "gv_index" not in mapping:
        LOGGER.warning("Ignoring entity state mapping for %s without gv_index", entity_id)
        return

    try:
        gv_index = config_int(mapping, "gv_index", 0, 0, 31)
    except ValueError as error:
        LOGGER.error("Ignoring entity state mapping for %s: %s", entity_id, error)
        return

    raw_value = get_mapping_source_value(mapping, state_data)
    gv_value = map_state_value_to_gv(mapping, raw_value)
    if gv_value is None:
        LOGGER.warning(
            "Could not map state for %s to _GV%s: %s",
            entity_id,
            gv_index,
            raw_value,
        )
        return

    LOGGER.info(
        "Syncing %s=%s to _GV%s=%s",
        entity_id,
        raw_value,
        gv_index,
        gv_value,
    )
    run_configured_hid_command(
        {
            "hid_command": "write_gv",
            "gv_index": gv_index,
            "gv_value": gv_value,
        },
        hidraw_path,
        enable_hid_commands,
        f"entity state mapping for {entity_id}",
    )


def sync_entity_state_mapping(
    mapping: dict[str, Any],
    headers: dict[str, str] | None,
    api_base_url: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    entity_id = as_optional_string(mapping.get("entity_id"))
    if not entity_id:
        LOGGER.warning("Ignoring entity state mapping without entity_id: %s", mapping)
        return

    state_data = get_home_assistant_entity_state(entity_id, headers, api_base_url)
    if state_data is None:
        return

    sync_entity_state_mapping_with_state_data(
        mapping,
        state_data,
        entity_id,
        hidraw_path,
        enable_hid_commands,
    )


def sync_entity_state_mappings_once(
    mappings: list[Any],
    headers: dict[str, str] | None,
    api_base_url: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    if not mappings:
        return
    if not isinstance(mappings, list):
        LOGGER.warning("Ignoring entity_state_mappings because it is not a list")
        return

    for mapping in mappings:
        if not isinstance(mapping, dict):
            LOGGER.warning("Ignoring invalid entity state mapping: %s", mapping)
            continue
        sync_entity_state_mapping(
            mapping,
            headers,
            api_base_url,
            hidraw_path,
            enable_hid_commands,
        )


def entity_state_sync_loop(
    interval_seconds: int,
    mappings: list[Any],
    headers: dict[str, str] | None,
    api_base_url: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    while True:
        time.sleep(interval_seconds)
        try:
            sync_entity_state_mappings_once(
                mappings,
                headers,
                api_base_url,
                hidraw_path,
                enable_hid_commands,
            )
        except Exception:
            LOGGER.exception("Unexpected error while syncing entity states")


def start_entity_state_sync_thread(
    interval_seconds: int,
    mappings: list[Any],
    headers: dict[str, str] | None,
    api_base_url: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    if not mappings or interval_seconds <= 0:
        return

    LOGGER.info("Starting entity state sync every %s second(s)", interval_seconds)
    thread = threading.Thread(
        target=entity_state_sync_loop,
        args=(
            interval_seconds,
            mappings,
            headers,
            api_base_url,
            hidraw_path,
            enable_hid_commands,
        ),
        daemon=True,
        name="entity-state-sync",
    )
    thread.start()


def build_entity_state_mapping_lookup(
    mappings: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(mappings, list):
        return lookup

    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        entity_id = as_optional_string(mapping.get("entity_id"))
        if not entity_id:
            continue
        lookup.setdefault(entity_id, []).append(mapping)

    return lookup


def receive_websocket_json(connection: websocket.WebSocket) -> dict[str, Any]:
    raw_message = connection.recv()
    try:
        message = json.loads(raw_message)
    except ValueError as error:
        raise ValueError(f"WebSocket message was not valid JSON: {raw_message}") from error
    if not isinstance(message, dict):
        raise ValueError(f"WebSocket message was not an object: {message}")
    return message


def send_websocket_json(
    connection: websocket.WebSocket,
    payload: dict[str, Any],
) -> None:
    connection.send(json.dumps(payload))


def authenticate_home_assistant_websocket(
    connection: websocket.WebSocket,
    token: str,
) -> None:
    message = receive_websocket_json(connection)

    if message.get("type") == "auth_required":
        send_websocket_json(
            connection,
            {
                "type": "auth",
                "access_token": token,
            },
        )
        message = receive_websocket_json(connection)

    if message.get("type") != "auth_ok":
        raise RuntimeError(f"Home Assistant WebSocket auth failed: {message}")


def subscribe_home_assistant_event(
    connection: websocket.WebSocket,
    request_id: int,
    event_type: str,
) -> None:
    send_websocket_json(
        connection,
        {
            "id": request_id,
            "type": "subscribe_events",
            "event_type": event_type,
        },
    )

    while True:
        message = receive_websocket_json(connection)
        if message.get("id") != request_id:
            continue
        if not message.get("success", False):
            raise RuntimeError(f"Could not subscribe to {event_type}: {message}")
        return


def handle_home_assistant_hid_command_event(
    event_data: dict[str, Any],
    command_event_type: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    command_config = dict(event_data)
    if "hid_command" not in command_config and "command" in command_config:
        command_config["hid_command"] = command_config["command"]

    command = normalize_hid_command(as_optional_string(command_config.get("hid_command")))
    if not command:
        LOGGER.warning("Ignoring %s event without hid_command", command_event_type)
        return

    run_configured_hid_command(
        command_config,
        hidraw_path,
        enable_hid_commands,
        f"Home Assistant event {command_event_type}",
    )


def handle_home_assistant_state_changed_event(
    event_data: dict[str, Any],
    mapping_lookup: dict[str, list[dict[str, Any]]],
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    entity_id = as_optional_string(event_data.get("entity_id"))
    if not entity_id:
        return

    mappings = mapping_lookup.get(entity_id)
    if not mappings:
        return

    new_state = event_data.get("new_state")
    if not isinstance(new_state, dict):
        LOGGER.warning("State event for %s has no usable new_state", entity_id)
        return

    for mapping in mappings:
        sync_entity_state_mapping_with_state_data(
            mapping,
            new_state,
            entity_id,
            hidraw_path,
            enable_hid_commands,
        )


def run_home_assistant_event_session(
    websocket_url: str,
    token: str,
    command_event_type: str,
    enable_ha_event_commands: bool,
    entity_state_mapping_lookup: dict[str, list[dict[str, Any]]],
    enable_entity_state_events: bool,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    connection = websocket.create_connection(
        websocket_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        authenticate_home_assistant_websocket(connection, token)

        request_id = 1
        if enable_ha_event_commands:
            subscribe_home_assistant_event(
                connection,
                request_id,
                command_event_type,
            )
            LOGGER.info(
                "Listening for Home Assistant HID command events: %s",
                command_event_type,
            )
            request_id += 1

        if enable_entity_state_events and entity_state_mapping_lookup:
            subscribe_home_assistant_event(connection, request_id, "state_changed")
            LOGGER.info("Listening for Home Assistant state_changed events")

        while True:
            try:
                message = receive_websocket_json(connection)
            except websocket.WebSocketTimeoutException:
                continue

            if message.get("type") != "event":
                continue

            event = message.get("event")
            if not isinstance(event, dict):
                continue

            event_type = as_optional_string(event.get("event_type"))
            event_data = event.get("data") or {}
            if not isinstance(event_data, dict):
                LOGGER.warning("Ignoring %s event with non-object data", event_type)
                continue

            if enable_ha_event_commands and event_type == command_event_type:
                handle_home_assistant_hid_command_event(
                    event_data,
                    command_event_type,
                    hidraw_path,
                    enable_hid_commands,
                )
            elif enable_entity_state_events and event_type == "state_changed":
                handle_home_assistant_state_changed_event(
                    event_data,
                    entity_state_mapping_lookup,
                    hidraw_path,
                    enable_hid_commands,
                )
    finally:
        connection.close()


def home_assistant_event_loop(
    websocket_url: str,
    token: str,
    command_event_type: str,
    enable_ha_event_commands: bool,
    entity_state_mapping_lookup: dict[str, list[dict[str, Any]]],
    enable_entity_state_events: bool,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    while True:
        try:
            LOGGER.info("Connecting to Home Assistant WebSocket: %s", websocket_url)
            run_home_assistant_event_session(
                websocket_url,
                token,
                command_event_type,
                enable_ha_event_commands,
                entity_state_mapping_lookup,
                enable_entity_state_events,
                hidraw_path,
                enable_hid_commands,
            )
        except websocket.WebSocketException as error:
            LOGGER.warning(
                "Home Assistant event listener disconnected: %s. Reconnecting in %s second(s)",
                error,
                HA_EVENT_RECONNECT_DELAY_SECONDS,
            )
        except Exception:
            LOGGER.exception(
                "Home Assistant event listener failed. Reconnecting in %s second(s)",
                HA_EVENT_RECONNECT_DELAY_SECONDS,
            )

        time.sleep(HA_EVENT_RECONNECT_DELAY_SECONDS)


def start_home_assistant_event_thread(
    websocket_url: str,
    command_event_type: str,
    enable_ha_event_commands: bool,
    entity_state_mappings: list[Any],
    enable_entity_state_events: bool,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    entity_state_mapping_lookup = build_entity_state_mapping_lookup(
        entity_state_mappings
    )
    if not enable_ha_event_commands and not (
        enable_entity_state_events and entity_state_mapping_lookup
    ):
        return

    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        LOGGER.warning(
            "Home Assistant event listener is enabled, but SUPERVISOR_TOKEN is missing"
        )
        return

    thread = threading.Thread(
        target=home_assistant_event_loop,
        args=(
            websocket_url,
            token,
            command_event_type,
            enable_ha_event_commands,
            entity_state_mapping_lookup,
            enable_entity_state_events,
            hidraw_path,
            enable_hid_commands,
        ),
        daemon=True,
        name="home-assistant-events",
    )
    thread.start()


def execute_mapping_actions(
    mapping: dict[str, Any],
    headers: dict[str, str] | None,
    api_base_url: str,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    call_home_assistant_service(mapping, headers, api_base_url)
    run_configured_hid_command(
        mapping,
        hidraw_path,
        enable_hid_commands,
        f"mapping for {mapping.get('key')}",
    )


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
    hidraw_path: str,
    enable_hid_commands: bool,
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
            execute_mapping_actions(
                mapping,
                headers,
                api_base_url,
                hidraw_path,
                enable_hid_commands,
            )
    finally:
        device.close()


def main() -> None:
    options = load_options()
    device_path = str(options["device_path"])
    debounce_seconds = max(0, int(options.get("debounce_ms", 500))) / 1000
    hidraw_path = str(options.get("hidraw_path", ""))
    enable_hid_debug = bool(options.get("enable_hid_debug", False))
    enable_hid_commands = bool(options.get("enable_hid_commands", False))
    enable_ha_event_commands = bool(options.get("enable_ha_event_commands", False))
    ha_event_command_type = (
        as_optional_string(options.get("ha_event_command_type"))
        or DEFAULT_HA_EVENT_COMMAND_TYPE
    )
    enable_entity_state_events = bool(options.get("enable_entity_state_events", False))
    hid_commands_on_start = options.get("hid_commands_on_start") or []
    entity_state_sync_interval = max(
        0,
        int(options.get("entity_state_sync_interval", 0)),
    )
    entity_state_mappings = options.get("entity_state_mappings") or []
    mappings = build_mapping_lookup(options["button_mappings"])
    headers = get_auth_headers()
    api_base_url = get_api_base_url()
    websocket_url = get_home_assistant_websocket_url(api_base_url)

    LOGGER.info("Using input device path: %s", device_path)
    LOGGER.info("Using Home Assistant API base URL: %s", api_base_url)
    LOGGER.info("Using debounce window: %.3f second(s)", debounce_seconds)
    LOGGER.info("HID commands are %s", "enabled" if enable_hid_commands else "disabled")
    LOGGER.info(
        "Home Assistant live HID command events are %s",
        "enabled" if enable_ha_event_commands else "disabled",
    )
    LOGGER.info(
        "Home Assistant state change events are %s",
        "enabled" if enable_entity_state_events else "disabled",
    )
    log_hidraw_diagnostics(hidraw_path, enable_hid_debug)
    run_startup_hid_commands(
        hid_commands_on_start,
        hidraw_path,
        enable_hid_commands,
    )
    sync_entity_state_mappings_once(
        entity_state_mappings,
        headers,
        api_base_url,
        hidraw_path,
        enable_hid_commands,
    )
    start_entity_state_sync_thread(
        entity_state_sync_interval,
        entity_state_mappings,
        headers,
        api_base_url,
        hidraw_path,
        enable_hid_commands,
    )
    start_home_assistant_event_thread(
        websocket_url,
        ha_event_command_type,
        enable_ha_event_commands,
        entity_state_mappings,
        enable_entity_state_events,
        hidraw_path,
        enable_hid_commands,
    )

    while True:
        try:
            read_device_events(
                device_path,
                mappings,
                headers,
                api_base_url,
                debounce_seconds,
                hidraw_path,
                enable_hid_commands,
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
