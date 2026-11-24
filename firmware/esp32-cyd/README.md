# busytag firmware: ESP32-2432S028 "Cheap Yellow Display"

Turns the CYD into a busytag status display with touch. It speaks the same JSON-lines
protocol as `firmware/esp32-c6-lcd`, so `busytag` drives it with `src/busytag/esp32.py`.
Taps that need the laptop (jump to an agent's terminal) are queued on the board and
collected by `busytag watch`.

## Board (verified 2026-11-23)

- ESP32-D0WD-V3 (rev v3.1), 240 MHz dual core, 4 MB flash, **no PSRAM**.
- USB is a CH340 bridge: VID `0x1A86`, PID `0x7523`, no USB serial number. The port is
  `/dev/cu.wchusbserial*`. `busytag` asks every WCH port `hello`.
- ILI9341 320x240 on HSPI: SCLK 14, MISO 12, MOSI 13, CS 15, DC 2. Backlight on 21 (PWM).
  This unit is the original single-USB CYD. The two-USB "CYD2USB" uses an ST7789 and needs
  a different driver.
- XPT2046 touch on its own pins, driven on VSPI: CLK 25, MISO 39, MOSI 32, CS 33, IRQ 36.
  VSPI is free because busytag doesn't use the SD card.
- RGB LED: red 4, green 16, blue 17, **active low**, driven with PWM.
- Portrait (240x320) both ways up: rotation 0 or 2 (`Flip` in Settings, or `busytag rotate`).

## Build and flash

From the repository root: `just cyd-build`, `just cyd-flash`, `just cyd-monitor`.
PlatformIO runs through `uvx --from platformio` with the same pioarduino platform as the C6.

- Upload runs at 115200: the CH340 dropped data at 460800 on this board.
- Brightness, rotation and the LED on/off setting are saved in NVS.
- **No PSRAM:** a full-screen 16-bit canvas (150 KB) is bigger than the largest free heap
  block, so the screen is drawn in four 80-row bands through one 38 KB canvas.
- The receive buffer is raised to 4 KB, as on the C6.
- Opening and closing the port didn't reset the board in testing (40 opens, pyserial
  defaults). If it ever resets, `busytag watch` sees `fresh` and redraws.

## Touch

| Screen | Taps |
|---|---|
| Agent list | Tap an agent for its details. `<` `>` page through more than five. `Settings`. |
| Agent details | Full detail text, state and age. `Jump to it` queues a jump (shown only when the agent's terminal is known). `Back`. |
| Settings | Brightness `-` `+`, status LED on/off, `Flip` (rotate 180°), `Sleep` (backlight off until the next tap or a new request for attention). |
| Idle or fill screen | `Settings` (a fill screen opens Settings anywhere). |

Detail and Settings return to the list after a minute without taps. Ages count up on the
board between pushes.

**Touch calibration** is in `TOUCH_X_MIN`... at the top of `src/main.cpp`. To check it, tap
somewhere and send `{"cmd":"touch"}`. The reply has the raw reading and the screen point.

## Protocol additions

Everything in the C6 README's table works the same. Also:

| Request | Effect |
|---|---|
| `{"cmd":"hello"}` | Also replies `"touch": true` and `board` `esp32-2432s028` |
| `{"cmd":"status",…}` | Rows may carry `[label, state, detail, "RRGGBB", agent_id, age_seconds, can_jump]`. Four-field rows still work (the label stands in for the ID, no jump). |
| `{"cmd":"events"}` | Replies `events` (queued taps, oldest first, e.g. `{"type":"jump","agent":"claude:…"}`) and clears them, plus `fresh`: true until the host draws something after a reset |
| `{"cmd":"touch"}` | Last press: `raw_x`, `raw_y`, `x`, `y`, `ms_ago` (for calibration) |

`rotate` accepts 0-3 but only uses portrait: 0 and 1 mean rotation 0, 2 and 3 mean rotation 2. Touch calibration stays in landscape (rotation 1) coordinates and is turned to portrait in `screen_point`.

## Restoring the factory demo

The CYD's factory flash (Sunton's LVGL demo) is backed up outside this repo, in
`~/projects/esp32/backups/flash-48aff36b21dc-20261123.bin`. To restore it:

```bash
uvx --from esptool esptool --port /dev/cu.wchusbserial110 --baud 115200 write-flash 0 ~/projects/esp32/backups/flash-48aff36b21dc-20261123.bin
```
