# HA DuckyPad

> **Experimental:** This repository is very experimental and was written with
> AI assistance. Review the code and test carefully before relying on it for
> important automations.

Home Assistant OS add-on for reading key events from a DuckyPad Pro USB input
device and triggering Home Assistant services.

This MVP focuses on reliable key input handling first. Experimental HID
commands can send a small set of documented commands back to the DuckyPad Pro.
Direct host-side OLED drawing is not implemented; OLED workflows use
DuckyScript on the device plus `_GV` values written by the add-on.

## What It Does

- Reads Linux input events with Python and `evdev`.
- Logs every key event with key name, key code, state, and value.
- Calls Home Assistant services on key-down events.
- Uses the Home Assistant add-on `SUPERVISOR_TOKEN`.
- Reconnects automatically if the USB device disappears and comes back.
- Ignores common modifier keys such as `KEY_LEFTMETA`.
- Debounces repeated key-down events to avoid accidental double triggers.
- Optionally logs safe HID diagnostics for future OLED/RGB experiments.
- Optionally sends documented DuckyPad HID commands when explicitly enabled.
- Optionally listens for Home Assistant events that trigger HID commands live,
  without restarting the add-on.
- Optionally syncs Home Assistant entity states into DuckyPad persistent global
  variables for OLED/RGB DuckyScript workflows.
- Optionally updates those variables immediately when Home Assistant state
  change events arrive.

## Default Device

```text
/dev/input/by-id/usb-dekuNukem_duckyPad_Pro_DP24_A1E7C3D4-event-kbd
```

The add-on maps `/dev/input` into the container so the configured input device
path can point to the stable `by-id` path.

## Default Button Mappings

```yaml
debounce_ms: 500
hidraw_path: /dev/hidraw0
enable_hid_debug: false
enable_hid_commands: false
enable_ha_event_commands: false
ha_event_command_type: ha_duckypad_hid_command
enable_entity_state_events: false
hid_commands_on_start: []
entity_state_sync_interval: 0
entity_state_mappings: []
button_mappings:
  - key: KEY_F13
    service: switch.toggle
    entity_id: switch.elegoo
  - key: KEY_F14
    service: switch.toggle
    entity_id: switch.voron
```

When any DuckyPad key is pressed, the add-on log includes a line like:

```text
Received key event: name=KEY_F13 code=183 state=key_down value=1
```

Mapped key-down events call the local Home Assistant REST API through:

```text
http://supervisor/core/api/services/<domain>/<service>
```

## Configuration

```yaml
device_path: /dev/input/by-id/usb-dekuNukem_duckyPad_Pro_DP24_A1E7C3D4-event-kbd
debounce_ms: 500
hidraw_path: /dev/hidraw0
enable_hid_debug: false
enable_hid_commands: false
enable_ha_event_commands: false
ha_event_command_type: ha_duckypad_hid_command
enable_entity_state_events: false
hid_commands_on_start: []
entity_state_sync_interval: 0
entity_state_mappings: []
button_mappings:
  - key: KEY_F13
    service: switch.toggle
    entity_id: switch.elegoo
  - key: KEY_F14
    service: switch.toggle
    entity_id: switch.voron
```

Each mapping uses:

- `key`: Linux input key name, for example `KEY_F13`.
- `service`: Home Assistant service in `domain.service` format.
- `entity_id`: Optional Home Assistant entity ID passed as service data.
- `debounce_ms`: Time window in milliseconds during which repeated key-down
  events for the same key are ignored.
- `hidraw_path`: Experimental HID raw device path for future DuckyPad output
  features.
- `enable_hid_debug`: Logs HID metadata and tests read-only access. This does
  not send commands to the DuckyPad.
- `enable_hid_commands`: Allows the add-on to write documented 64-byte HID
  command packets to `hidraw_path`. Default is `false`.
- `enable_ha_event_commands`: Allows Home Assistant events to trigger HID
  commands while the add-on is running. Default is `false`.
- `ha_event_command_type`: Event type the add-on listens for when live HID
  commands are enabled. Default is `ha_duckypad_hid_command`.
- `enable_entity_state_events`: Uses Home Assistant `state_changed` events to
  update configured `_GV` mappings immediately. Default is `false`.
- `hid_commands_on_start`: Optional list of HID commands to send once when the
  add-on starts.
- `entity_state_mappings`: Optional list of Home Assistant entity states to
  write into DuckyPad `_GV0` to `_GV31`.
- `entity_state_sync_interval`: Optional refresh interval in seconds. `0`
  disables periodic refresh; mappings still sync once at startup.

## Experimental HID Commands

HID commands are based on the official DuckyPad HID command protocol:

```text
https://github.com/duckyPad/duckyPad-Profile-Autoswitcher/blob/master/HID_details.md
```

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

Example startup commands:

```yaml
enable_hid_commands: true
hid_commands_on_start:
  - hid_command: get_info
  - hid_command: set_rtc
```

Example key mapping that changes one DuckyPad LED:

```yaml
button_mappings:
  - key: KEY_F15
    hid_command: set_rgb
    led_index: 0
    red: 0
    green: 64
    blue: 255
```

Example key mapping that writes a persistent global variable:

```yaml
button_mappings:
  - key: KEY_F16
    hid_command: write_gv
    gv_index: 0
    gv_value: 1
```

For OLED workflows, use `write_gv` to send numeric state into `_GV0` to
`_GV31`, then use DuckyScript on the DuckyPad to read those values and draw on
the OLED with `OLED_PRINT`, `OLED_CLEAR`, and `OLED_UPDATE`.

## Live HID Commands from Home Assistant

Enable the live event listener:

```yaml
enable_hid_commands: true
enable_ha_event_commands: true
ha_event_command_type: ha_duckypad_hid_command
```

Then fire a Home Assistant event with the same fields used by a configured
`hid_command`.

Example script action that changes one LED:

```yaml
sequence:
  - event: ha_duckypad_hid_command
    event_data:
      hid_command: set_rgb
      led_index: 0
      red: 0
      green: 64
      blue: 255
mode: single
```

Example script action that writes `_GV2=42`:

```yaml
sequence:
  - event: ha_duckypad_hid_command
    event_data:
      hid_command: write_gv
      gv_index: 2
      gv_value: 42
mode: single
```

You can also test from Developer Tools -> Events by firing
`ha_duckypad_hid_command` with JSON event data:

```json
{"hid_command":"get_info"}
```

A complete example script lives at:

```text
ha-duckypad/examples/home_assistant_live_hid_script.yaml
```

More copy-and-adapt Home Assistant examples live at:

```text
ha-duckypad/examples/home_assistant_scripts.yaml
ha-duckypad/examples/home_assistant_automations.yaml
```

## Entity State Sync to DuckyPad GV

The add-on can read Home Assistant entity states and write them to DuckyPad
persistent global variables. This is the easiest bridge for OLED display
workflows.

Example: sync two switches to `_GV0` and `_GV1` every 10 seconds:

```yaml
enable_hid_commands: true
entity_state_sync_interval: 10
enable_entity_state_events: true
entity_state_mappings:
  - entity_id: switch.elegoo
    gv_index: 0
    state_type: bool
  - entity_id: switch.voron
    gv_index: 1
    state_type: bool
```

For `state_type: bool`, common states such as `on`, `open`, `home`, and `true`
become `1`; `off`, `closed`, `not_home`, and `false` become `0`.

For numeric sensors, use `state_type: number`:

```yaml
entity_state_mappings:
  - entity_id: sensor.living_room_temperature
    gv_index: 2
    state_type: number
```

To read an attribute instead of the main state:

```yaml
entity_state_mappings:
  - entity_id: weather.home
    attribute: temperature
    gv_index: 3
    state_type: number
```

Example DuckyScript for the OLED lives at:

```text
ha-duckypad/examples/oled_gv_status.txt
```

For a status screen that stays visible, use:

```text
ha-duckypad/examples/oled_live_switch_status_loop.txt
```

Enable the DuckyPad Configurator "Allow Abort" option for looping OLED scripts
so the key can be interrupted from the device.

## PC Commands With HASS.Agent

To trigger commands on a Windows PC, create a HASS.Agent command as a Home
Assistant button entity, then map a DuckyPad key to `button.press`:

```yaml
button_mappings:
  - key: KEY_F12
    service: button.press
    entity_id: button.start_calc
```

If the DuckyPad key sends modifier keys such as `KEY_LEFTMETA` together with
the real key, the add-on logs the event but ignores the modifier for mapping.

## Experimental HID Diagnostics

The DuckyPad Pro may expose an additional HID raw device such as:

```text
/dev/hidraw0
```

Enable diagnostics to check whether the add-on can see and open that device:

```yaml
hidraw_path: /dev/hidraw0
enable_hid_debug: true
```

This mode only logs device metadata and performs a read-only open test. It does
not write to the device. HID writes require `enable_hid_commands: true`.

## Example Files

The `examples/` folder contains small building blocks:

- `addon_options_comfort.yaml`: add-on options for live events, `_GV` sync, and
  a few sample button mappings.
- `home_assistant_live_hid_script.yaml`: quick live HID smoke test.
- `home_assistant_scripts.yaml`: reusable scripts for wake, RTC sync, GV sync,
  RGB, and opening Home Assistant on a PC through HASS.Agent.
- `home_assistant_automations.yaml`: example automations that react to
  `switch.elegoo` and `switch.voron`.
- `oled_gv_status.txt`: short one-shot OLED status display.
- `oled_live_switch_status_loop.txt`: looping OLED display for `_GV0` and
  `_GV1`.
- `oled_macro_confirm_once.txt`: short confirmation screen after a macro.

## Repository Layout

```text
repository.yaml
ha-duckypad/
  config.yaml
  Dockerfile
  run.sh
  app.py
  README.md
```

Add this GitHub repository as a Home Assistant add-on repository, then install
the `HA DuckyPad` add-on from the add-on store.
