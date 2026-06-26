# HA DuckyPad

> **Experimental:** This repository is very experimental and was written with
> AI assistance. Review the code and test carefully before relying on it for
> important automations.

Home Assistant OS add-on for reading key events from a DuckyPad Pro USB input
device and triggering Home Assistant services.

This MVP focuses on reliable key input handling only. It does not control the
DuckyPad display or RGB lighting.

## What It Does

- Reads Linux input events with Python and `evdev`.
- Logs every key event with key name, key code, state, and value.
- Calls Home Assistant services on key-down events.
- Uses the Home Assistant add-on `SUPERVISOR_TOKEN`.
- Reconnects automatically if the USB device disappears and comes back.

## Default Device

```text
/dev/input/by-id/usb-dekuNukem_duckyPad_Pro_DP24_A1E7C3D4-event-kbd
```

The add-on maps `/dev/input` into the container so the configured input device
path can point to the stable `by-id` path.

## Default Button Mappings

```yaml
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
