# HA DuckyPad

> **Experimental:** This repository is very experimental and was written with
> AI assistance. Review the code and test carefully before relying on it for
> important automations.

Home Assistant OS add-on for reading key events from a DuckyPad Pro USB input
device and triggering Home Assistant services.

This MVP focuses on reliable key input handling first. Experimental HID
commands can send a small set of documented commands back to the DuckyPad Pro,
but direct OLED drawing is not implemented.

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
hid_commands_on_start: []
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
hid_commands_on_start: []
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
- `hid_commands_on_start`: Optional list of HID commands to send once when the
  add-on starts.

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
