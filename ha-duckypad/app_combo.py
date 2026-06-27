#!/usr/bin/env python3

import time
from typing import Any

import app
from evdev import InputDevice, categorize, ecodes

MODIFIER_ALIASES = {
    "KEY_LEFTCTRL": "CTRL",
    "KEY_RIGHTCTRL": "CTRL",
    "KEY_LEFTSHIFT": "SHIFT",
    "KEY_RIGHTSHIFT": "SHIFT",
    "KEY_LEFTALT": "ALT",
    "KEY_RIGHTALT": "ALT",
    "KEY_LEFTMETA": "META",
    "KEY_RIGHTMETA": "META",
}
MODIFIER_ORDER = ["CTRL", "SHIFT", "ALT", "META"]
MODIFIER_NAME_ALIASES = {
    "CONTROL": "CTRL",
    "CTRL": "CTRL",
    "SHIFT": "SHIFT",
    "ALT": "ALT",
    "OPTION": "ALT",
    "META": "META",
    "WIN": "META",
    "WINDOWS": "META",
    "CMD": "META",
    "COMMAND": "META",
    "SUPER": "META",
}


def normalize_mapping_key(key: str) -> str:
    parts = [part.strip().upper() for part in key.replace("-", "+").split("+")]
    modifiers: set[str] = set()
    base_key = ""

    for part in parts:
        if not part:
            continue
        modifier = MODIFIER_NAME_ALIASES.get(part)
        if modifier:
            modifiers.add(modifier)
            continue
        base_key = part

    if not base_key:
        return "+".join(modifier for modifier in MODIFIER_ORDER if modifier in modifiers)

    ordered_modifiers = [modifier for modifier in MODIFIER_ORDER if modifier in modifiers]
    return "+".join([*ordered_modifiers, base_key]) if ordered_modifiers else base_key


def build_mapping_lookup_with_combos(mappings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}

    for mapping in mappings:
        key = app.as_optional_string(mapping.get("key"))
        service = app.as_optional_string(mapping.get("service"))
        hid_command = app.as_optional_string(mapping.get("hid_command"))

        if not key or (not service and not hid_command):
            app.LOGGER.warning("Ignoring incomplete mapping: %s", mapping)
            continue

        lookup[normalize_mapping_key(key)] = mapping

    app.LOGGER.info("Loaded %d button mapping(s)", len(lookup))
    return lookup


def build_event_key(active_modifiers: set[str], key_name: str) -> str:
    ordered_modifiers = [modifier for modifier in MODIFIER_ORDER if modifier in active_modifiers]
    key = key_name.upper()
    return "+".join([*ordered_modifiers, key]) if ordered_modifiers else key


def read_device_events_with_combos(
    device_path: str,
    mappings: dict[str, dict[str, Any]],
    headers: dict[str, str] | None,
    api_base_url: str,
    debounce_seconds: float,
    hidraw_path: str,
    enable_hid_commands: bool,
) -> None:
    app.wait_for_device(device_path)
    device = InputDevice(device_path)
    app.LOGGER.info("Connected to input device: %s (%s)", device.name, device.path)
    last_triggered_at: dict[str, float] = {}
    active_modifiers: set[str] = set()

    try:
        for event in device.read_loop():
            if event.type != ecodes.EV_KEY:
                continue

            key_event = categorize(event)
            key_name = app.normalize_keycode(key_event.keycode)
            key_value = event.value
            state_name = {
                0: "key_up",
                1: "key_down",
                2: "key_hold",
            }.get(key_value, f"value_{key_value}")

            app.LOGGER.info(
                "Received key event: name=%s code=%s state=%s value=%s",
                key_name,
                event.code,
                state_name,
                key_value,
            )

            modifier = MODIFIER_ALIASES.get(key_name.upper())
            if modifier:
                if key_value in {app.KEY_DOWN, 2}:
                    active_modifiers.add(modifier)
                else:
                    active_modifiers.discard(modifier)
                continue

            if key_value != app.KEY_DOWN:
                continue

            plain_key = key_name.upper()
            combo_key = build_event_key(active_modifiers, key_name)
            mapping = mappings.get(combo_key)
            trigger_key = combo_key

            if not mapping and combo_key != plain_key:
                mapping = mappings.get(plain_key)
                trigger_key = plain_key

            if not mapping:
                app.LOGGER.info("No mapping configured for %s", combo_key)
                continue

            if combo_key != plain_key:
                app.LOGGER.info("Resolved key combo %s to mapping %s", combo_key, trigger_key)

            now = time.monotonic()
            previous_triggered_at = last_triggered_at.get(trigger_key, 0)
            if debounce_seconds > 0 and now - previous_triggered_at < debounce_seconds:
                app.LOGGER.info("Ignoring %s because it is inside the debounce window", trigger_key)
                continue

            last_triggered_at[trigger_key] = now
            app.execute_mapping_actions(
                mapping,
                headers,
                api_base_url,
                hidraw_path,
                enable_hid_commands,
            )
    finally:
        device.close()


app.build_mapping_lookup = build_mapping_lookup_with_combos
app.read_device_events = read_device_events_with_combos

if __name__ == "__main__":
    app.main()
