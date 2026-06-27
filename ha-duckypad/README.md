# HA DuckyPad

> **Experimental:** This repository is very experimental and was written with AI assistance. Review the code and test carefully before relying on it for important automations.

Home Assistant OS add-on for reading key events from a DuckyPad Pro USB input device and triggering Home Assistant services. Experimental HID commands can also send a small set of documented commands back to the DuckyPad Pro.

## Central Button File

The easiest way to manage buttons is one file:

```text
/share/ha-duckypad/buttons.yaml
```

The add-on creates a starter file there on first run. Edit that file, restart the add-on, done. You no longer need to jump through the long add-on options list for every new button.

Example:

```yaml
button_mappings:
  - key: KEY_F12
    action: button.windowspc_start_calc
  - key: KEY_F13
    action: switch.elegoo
  - key: KEY_F14
    action: switch.voron
  - key: KEY_F15
    action: script.duckypad_open_home_assistant_on_pc
```

The file can also contain the comfort options you use often:

```yaml
enable_hid_commands: true
enable_ha_event_commands: true
enable_entity_state_events: true
entity_state_sync_interval: 10
entity_state_mappings:
  - entity_id: switch.elegoo
    gv_index: 0
    state_type: bool
  - entity_id: switch.voron
    gv_index: 1
    state_type: bool
button_mappings:
  - key: KEY_F13
    action: switch.elegoo
  - key: KEY_F14
    action: switch.voron
  - key: KEY_F16
    action: hid:wake
```

If you want a different location, change `mapping_config_path` in the add-on options. JSON also works, but YAML is nicer to edit by hand.

## Action Shortcuts

For normal Home Assistant actions you can use the short `action` form. The add-on expands common entity domains automatically:

- `switch.example` -> `switch.toggle`
- `button.example` -> `button.press`
- `input_button.example` -> `input_button.press`
- `script.example` -> `script.turn_on`
- `scene.example` -> `scene.turn_on`
- `automation.example` -> `automation.trigger`

DuckyPad HID commands can use the same shortcut style when HID commands are enabled:

```yaml
enable_hid_commands: true
button_mappings:
  - key: KEY_F16
    action: hid:wake
  - key: KEY_F17
    action: hid:set_rtc
```

The old explicit form still works and is useful for unusual services:

```yaml
button_mappings:
  - key: KEY_F13
    service: switch.toggle
    entity_id: switch.elegoo
```

For multi-step macros, create a Home Assistant script and map the key to that script with `action: script.your_script_name`.

## Quick Setup

```yaml
mapping_config_path: /share/ha-duckypad/buttons.yaml
hidraw_path: auto
debounce_ms: 500
enable_hid_commands: true
enable_ha_event_commands: true
enable_entity_state_events: true
entity_state_sync_interval: 10
```

On startup, the log should show something like:

```text
[easy-actions] Loaded button_mappings from /share/ha-duckypad/buttons.yaml
Using HID raw path setting: auto -> /dev/hidraw0
```

If auto-detection cannot find the DuckyPad HID raw device, set `hidraw_path` manually to the path shown by Home Assistant, for example `/dev/hidraw0`.

## Default Device

```text
/dev/input/by-id/usb-dekuNukem_duckyPad_Pro_DP24_A1E7C3D4-event-kbd
```

When any DuckyPad key is pressed, the add-on log includes a line like:

```text
Received key event: name=KEY_F13 code=183 state=key_down value=1
```

## Features

- Reads Linux input events with Python and `evdev`.
- Logs every key event with key name, key code, state, and value.
- Calls Home Assistant services on key-down events.
- Uses the Home Assistant add-on `SUPERVISOR_TOKEN`.
- Reconnects automatically if the USB device disappears and comes back.
- Ignores common modifier keys such as `KEY_LEFTMETA`.
- Debounces repeated key-down events to avoid accidental double triggers.
- Supports optional DuckyPad HID commands.
- Supports Home Assistant events that trigger HID commands live.
- Supports syncing Home Assistant entity states into DuckyPad `_GV` variables for OLED/RGB DuckyScript workflows.

## HID Commands

Supported command names:

- `get_info`
- `set_rtc`
- `set_rgb`
- `next_profile`
- `previous_profile`
- `goto_profile_number`
- `goto_profile_name`
- `sleep`
- `wake`
- `dump_gv`
- `write_gv`

Example live event from Home Assistant Developer Tools -> Events:

```json
{"hid_command":"get_info"}
```

Use event type:

```text
ha_duckypad_hid_command
```

## Entity State Sync to DuckyPad GV

Example: sync two switches to `_GV0` and `_GV1`:

```yaml
enable_hid_commands: true
enable_entity_state_events: true
entity_state_sync_interval: 10
entity_state_mappings:
  - entity_id: switch.elegoo
    gv_index: 0
    state_type: bool
  - entity_id: switch.voron
    gv_index: 1
    state_type: bool
```

For OLED workflows, use `write_gv` or entity state sync to send numeric state into `_GV0` to `_GV31`, then use DuckyScript on the DuckyPad to read those values and draw on the OLED with `OLED_PRINT`, `OLED_CLEAR`, and `OLED_UPDATE`.

## PC Commands With HASS.Agent

Create a HASS.Agent command as a Home Assistant button entity, then map a DuckyPad key to that button:

```yaml
button_mappings:
  - key: KEY_F12
    action: button.windowspc_start_calc
```

If the DuckyPad key sends modifier keys such as `KEY_LEFTMETA` together with the real key, the add-on logs the event but ignores the modifier for mapping.

## Example Files

- `examples/buttons.yaml`: central mapping file example for `/share/ha-duckypad/buttons.yaml`.
- `examples/addon_options_easy_actions.yaml`: shortest setup examples using `action`.
- `examples/addon_options_comfort.yaml`: live events, `_GV` sync, and sample button mappings.
- `examples/home_assistant_live_hid_script.yaml`: quick live HID smoke test.
- `examples/home_assistant_scripts.yaml`: reusable scripts for wake, RTC sync, GV sync, RGB, and opening Home Assistant on a PC through HASS.Agent.
- `examples/home_assistant_automations.yaml`: example automations that react to `switch.elegoo` and `switch.voron`.
- `examples/oled_gv_status.txt`: short one-shot OLED status display.
- `examples/oled_live_switch_status_loop.txt`: looping OLED display for `_GV0` and `_GV1`.
- `examples/oled_macro_confirm_once.txt`: short confirmation screen after a macro.

## Repository Layout

```text
repository.yaml
ha-duckypad/
  config.yaml
  Dockerfile
  run.sh
  app.py
  easy_actions.py
  README.md
```

Add this GitHub repository as a Home Assistant add-on repository, then install the `HA DuckyPad` add-on from the add-on store.
