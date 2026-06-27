#!/usr/bin/env python3

import json
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("/data/options.json")

QUICK_ACTION_SERVICE_DEFAULTS = {
    "automation": "automation.trigger",
    "button": "button.press",
    "input_button": "input_button.press",
    "scene": "scene.turn_on",
    "script": "script.turn_on",
    "switch": "switch.toggle",
}

HID_COMMANDS = {
    "get_info",
    "goto_profile_number",
    "previous_profile",
    "prev_profile",
    "next_profile",
    "set_rgb",
    "sleep",
    "wake",
    "wake_up",
    "goto_profile_name",
    "dump_gv",
    "write_gv",
    "set_rtc",
}


def as_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_hid_command(command: str) -> str:
    return command.strip().lower().replace("-", "_")


def infer_action(action: str) -> dict[str, str]:
    action_text = as_string(action)
    if not action_text:
        return {}

    action_lower = action_text.lower()
    if action_lower.startswith(("hid:", "duckypad:")):
        _, hid_command = action_text.split(":", 1)
        return {"hid_command": normalize_hid_command(hid_command)}

    normalized_hid_command = normalize_hid_command(action_text)
    if normalized_hid_command in HID_COMMANDS:
        return {"hid_command": normalized_hid_command}

    if "." not in action_text:
        return {}

    domain = action_text.split(".", 1)[0]
    service = QUICK_ACTION_SERVICE_DEFAULTS.get(domain)
    if not service:
        return {}

    return {"service": service, "entity_id": action_text}


def expand_button_mapping(mapping: Any) -> Any:
    if not isinstance(mapping, dict):
        return mapping

    if as_string(mapping.get("service")) or as_string(mapping.get("hid_command")):
        return mapping

    action = as_string(mapping.get("action"))
    if not action:
        return mapping

    expanded = dict(mapping)
    expanded.pop("action", None)
    inferred = infer_action(action)
    if not inferred:
        print(f"[easy-actions] Could not infer action for {mapping!r}", flush=True)
        return mapping

    inferred.update(expanded)
    return inferred


def main() -> None:
    if not CONFIG_PATH.exists():
        return

    with CONFIG_PATH.open("r", encoding="utf-8") as options_file:
        options = json.load(options_file)

    mappings = options.get("button_mappings")
    if not isinstance(mappings, list):
        return

    expanded_mappings = [expand_button_mapping(mapping) for mapping in mappings]
    if expanded_mappings == mappings:
        return

    options["button_mappings"] = expanded_mappings
    with CONFIG_PATH.open("w", encoding="utf-8") as options_file:
        json.dump(options, options_file, indent=2)
        options_file.write("\n")

    print("[easy-actions] Expanded button action shortcuts", flush=True)


if __name__ == "__main__":
    main()
