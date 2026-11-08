# CLAUDE.md — busytag

## What this project is

A command-line tool, and later a TUI, for controlling a **Busy Tag** USB status display
(original hardware, made by SIA BUSY TAG / Greynut). It has two parts:

1. **Control CLI**: commands like `busytag image show <file>`, `busytag led color FF0000`,
   `busytag led pattern "Red Pulses"`, `busytag brightness 50`, `busytag upload <file>`,
   `busytag info`.
2. **Agent status display (the end goal)**: AI agents running on this laptop (Claude Code
   and others) show their state on the device: working, done, or needs attention. The user
   can then see when their attention is needed even while on another tab or macOS Space.

The command is named `busytag`, not `busybox`: BusyBox is a well-known Unix tool, and the
name would be confusing and collide on `PATH`.

## Reference material

- `notes`: links from the user
- `DEVICE.md`: everything verified on the connected unit (IDs, file list, every probed
  command and its reply, built-in pattern IDs). **Check it before trusting the online docs.**
- Protocol for this firmware: https://busy-tag.github.io/hardware/at-commands-v2 (2.x).
  The `/hardware/at-commands` page is for 3.x; some of it doesn't apply here.
- GitHub: https://github.com/busy-tag. `busytag-python-examples` (pyserial helper `busytag.py`)
  and `busytag-cli` (C#/.NET) are useful prior art.
- `device-backup/fw1.0-20261108/`: files copied off the device before the firmware upgrade.
  **Git-ignore it**: it contains `wifi_config.json`.

## Device facts (firmware 2.0)

- Firmware **2.0** (upgraded from 1.0 on 2026-11-08 with the Busy Tag app). Hardware 1.0.
  This is the original hardware, so **2.x is the ceiling**: no 3.x, no Wi-Fi, no HTTP API,
  even though the ESP32-S3 has the radio.
- USB VID `0x303a` / PID `0x81df`, serial `9C139EEDC770`. Find the port by VID/PID with
  `serial.tools.list_ports`; don't hardcode `/dev/cu.usbmodem9C139EEDC7701`. Always open
  `cu.*`, not `tty.*`.
- **Serial is the only interface.** Since 2.0 there is no USB drive. Upload images with
  `AT+UF=<file>,<size>`: wait for `>`, then send exactly `<size>` raw bytes.
- 460800 baud, 8N1, commands end with `\r\n`.
- **The serial port is exclusive.** If the Busy Tag desktop app is running, it holds the
  port. Report that clearly instead of failing with a cryptic error.

### Reading replies

- Data comes in `+PREFIX:data` lines. Multi-line queries (`AT+GFL`, `AT+GPL`, `AT+CP?`,
  `AT+GDPL`) end with `OK`. **Single-value queries (`AT+GFV` → `+FV:2.0`) have no `OK` after
  them.** End a read on `OK`, `ERROR:<n>`, or the expected `+PREFIX:` line for single-value
  queries.
- Unknown command → `ERROR:1`. Error codes are listed in the AT manual (2 invalid arg,
  3 file not found, 4 invalid size, 13 file-receive timeout, …).
- Ignore `+evn:` (events, e.g. `+evn:SP,<file>` after showing an image) and `+log:` lines
  while waiting for a reply.

### Capabilities

- Display: 240×280, PNG or animated GIF (GIFs ≤ ~1 MB). `AT+SP=<file>` shows an image;
  `AT+DC=<RRGGBB>` fills the screen with a solid color; `AT+DB=<n>` sets brightness.
- LEDs: 7, addressed by bitmask `led_bits` (`1` … `64`, `127` = all). Colors are `RRGGBB`.
  - `AT+SC=<led_bits>,<RRGGBB>`: solid color
  - `AT+DP=<id>`: **loads** built-in pattern 0–28 into the single custom-pattern slot
    (overwriting it) but doesn't play it; follow with `AT+PP=1,<repeat>`. 25–28 aren't in the docs.
  - Custom pattern: use `AT+CPD=+CP:<leds>,<RRGGBB>,<speed>,<delay>\r\n+CP:…`. The separator
    is the literal 4 characters `\r\n`. **Don't use `AT+CP=<n>` with the `>` prompt**: on 2.0 it
    stores only some steps, or none.
  - `AT+PP=<play>,<repeat>` plays the slot (255 = forever, `0,0` stops).
- `AT+DF` returns `ERROR:0` for the image currently on screen; show another image first.
- Events (`+evn:SP,…`) can arrive **after** `OK`; clear the input buffer before each command.
- Storage: ~3 MB total, ~920 KB free. Check `AT+GFSS` before uploading.
- 3.x-only commands return `ERROR:1` here: `AT+DD`, `AT+DDC`, `AT+SM`, `AT+TB`, `AT+WM`,
  `AT+GUSBS`, and all Wi-Fi and HTTP commands.
- Verified on the device: `AT+SP=`, `AT+DC=`, `AT+DB=`, `AT+SC=`, `AT+DP=`, `AT+PP=`,
  `AT+CPD=`, `AT+UF=`, `AT+DF=`.

## Tech stack

This project overrides the global Rails/React defaults. It is a local hardware tool.

- **Python 3.12+, managed with `uv`.** Never call `python`/`pip` directly; use `uv run`,
  `uv add`.
- `pyserial` for the device, `typer` for the CLI, `textual` for the TUI (later phase),
  `pillow` to resize or convert images to 240×280 before upload.
- Tests: `pytest` with a fake serial transport. Hardware tests are marked `@pytest.mark.device`
  and skipped by default.
- Task runner: `justfile` with a `default` recipe that lists recipes, as the first recipe.

## Architecture

```
src/busytag/
  device.py     # transport (find port, run/query/query_list/raw) + device API
  colors.py     # color names/hex, LED selection → mask
  images.py     # fit static images to 240x280 PNG; GIFs pass through with warnings
  cli.py        # info, brightness, files, raw, image {…}, led {…}, status, agents, hook
  status.py     # agent state store, most-urgent aggregation, LED plan, device push
  config.py     # ~/.config/busytag/config.toml: LED brightness, per-agent-type colors
  render.py     # draws the 240x280 status screen (headline, reason, agent list)
  hooks.py      # Claude Code hook event (stdin JSON) → status update
  tui.py        # Later: textual dashboard
hooks/claude-settings.json  # hook block to merge into ~/.claude/settings.json
tests/          # FakeSerial / FakeDevice, no hardware needed; `just test`
```

- **No daemon.** Each `busytag status` / `busytag hook` call takes an exclusive `flock` on
  `~/.cache/busytag/lock` (`BUSYTAG_STATE_DIR`), updates `state.json`, and opens the serial
  port only if the screen should change. The lock also serializes device access.
- **Aggregation:** `attention` > `error` > `done` > `working` > `idle`; idle agents aren't
  shown. Reports carry their start time and older ones are ignored, because async hooks can
  finish out of order. Agents silent for 12 h are dropped.
- **Screen updates** take ~1 s (upload + show). The device won't overwrite the image it is
  showing (`ERROR:3`), so status images alternate between `bt_status0.png` and `bt_status1.png`.
- **LEDs:** color = the most urgent agent's type color (config, keyed by the ID prefix
  before `:`); effect = state (attention pulses, done solid, working 25%, error solid red).
  There is no LED brightness command (`AT+LB?` etc. return `ERROR:1`), so `[leds] brightness`
  scales every color busytag sends. Brightness is part of the screen key, so changing it
  re-pushes. Status files: pick the one **not on screen per `AT+SP?`**, not per state.json.
- **Home:** on the first status push, the user's image, LED color and custom pattern are saved
  in `state.json` and restored when no agents are active (`busytag agents --reset` forces it).
- **Device errors** (unplugged, Busy Tag app holding the port) never lose the report: they
  are stored as `last_error`, logged to `hook.log` by hooks, and the next update retries.
- **Claude Code hooks** run with `"async": true`. Agent ID is `claude:<session_id>`; label is
  the project folder name. No event fires when the user approves a permission prompt, so
  `attention` clears on the next Pre/PostToolUse, prompt, or Stop.

## Conventions

- 2-space indentation; snake_case functions and variables; CamelCase classes.
- Keep it simple: no abstractions until a second firmware or agent type actually needs them.
- Before uploading or deleting on the device, check free space (`AT+GFSS`) and existing
  files (`AT+GPL`).
- Ask the user before destructive device commands: `AT+FD` (format), `AT+FR` (factory reset),
  `AT+DF` (delete file), or any firmware change.
- **Never write `wifi_config.json` contents (Wi-Fi password) into the repo, logs, or docs.**
- In zsh, quote AT commands that contain `?` (`busytag raw 'AT+SP?'`), or zsh treats `?`
  as a glob.
