#!/usr/bin/env python3

import json
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path("/data/options.json")
DEFAULT_MAPPING_CONFIG_PATH = "/share/ha-duckypad/buttons.yaml"
EXTERNAL_CONFIG_KEYS = {
    "button_mappings",
    "hid_commands_on_start",
    "entity_state_mappings",
    "entity_state_sync_interval",
    "enable_hid_commands",
    "enable_ha_event_commands",
    "enable_entity_state_events",
    "ha_event_command_type",
    "hidraw_path",
    "debounce_ms",
}

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


def load_structured_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as config_file:
        if path.suffix.lower() == ".json":
            return json.load(config_file)
        return yaml.safe_load(config_file)


def write_default_mapping_file(path: Path, options: dict[str, Any]) -> None:
    if path.exists():
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        mappings = options.get("button_mappings") or []
        path.write_text(
            "# HA DuckyPad button mappings\n"
            "# Edit this file instead of jumping through the add-on UI.\n"
            "# After saving changes, restart the HA DuckyPad add-on.\n\n"
            "button_mappings:\n"
            + yaml.safe_dump(mappings, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        print(f"[easy-actions] Created button mapping template at {path}", flush=True)
    except OSError as error:
        print(f"[easy-actions] Could not create mapping template at {path}: {error}", flush=True)


def merge_external_config(options: dict[str, Any]) -> dict[str, Any]:
    configured_path = as_string(options.get("mapping_config_path")) or DEFAULT_MAPPING_CONFIG_PATH
    if not configured_path:
        return options

    path = Path(configured_path)
    write_default_mapping_file(path, options)
    if not path.exists():
        return options

    try:
        external_config = load_structured_file(path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[easy-actions] Could not load mapping config {path}: {error}", flush=True)
        return options

    if external_config is None:
        print(f"[easy-actions] Mapping config {path} is empty", flush=True)
        return options

    merged_options = dict(options)
    if isinstance(external_config, list):
        merged_options["button_mappings"] = external_config
        print(f"[easy-actions] Loaded button mappings from {path}", flush=True)
        return merged_options

    if not isinstance(external_config, dict):
        print(f"[easy-actions] Ignoring mapping config {path}: expected object or list", flush=True)
        return options

    loaded_keys = []
    for key in EXTERNAL_CONFIG_KEYS:
        if key in external_config:
            merged_options[key] = external_config[key]
            loaded_keys.append(key)

    if loaded_keys:
        print(
            f"[easy-actions] Loaded {', '.join(sorted(loaded_keys))} from {path}",
            flush=True,
        )
    return merged_options


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

    options = merge_external_config(options)
    mappings = options.get("button_mappings")
    if isinstance(mappings, list):
        options["button_mappings"] = [expand_button_mapping(mapping) for mapping in mappings]

    with CONFIG_PATH.open("w", encoding="utf-8") as options_file:
        json.dump(options, options_file, indent=2)
        options_file.write("\n")

    print("[easy-actions] Prepared effective add-on options", flush=True)


if __name__ == "__main__":
    main()
