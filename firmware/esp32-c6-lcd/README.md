# busytag firmware: Waveshare ESP32-C6-LCD-1.47

Turns the board into a busytag status display. The host (`src/busytag/esp32.py`) sends
one JSON object per line, and the firmware draws the screen and runs the LED effect.

## Board (verified 2026-11-08)

- ESP32-C6FH8 (rev v0.2): RISC-V, 160 MHz, 8 MB embedded flash, no PSRAM.
- USB-C is the chip's built-in USB-Serial/JTAG: VID `0x303a`, PID `0x1001`. Every
  ESP32-C3/S3/C6 board has that ID, so busytag identifies the board with `hello`.
- ST7789 172x320 LCD: MOSI 6, SCLK 7, CS 14, DC 15, RST 21, backlight 22 (PWM). The
  panel sits at column offset 34, which Adafruit_ST7789 sets for 172 px wide.
- One WS2812 RGB LED on GPIO 8, wired in **RGB** order (the usual WS2812 order is GRB). microSD slot (not used).
- Landscape with the USB-C on the right is Adafruit rotation 3 (the default).

## Build and flash

From the repository root: `just fw-build`, `just fw-flash`, `just fw-monitor`.
PlatformIO runs through `uvx --from platformio` with the pioarduino platform (Arduino 3.x).

- Brightness and rotation are saved in NVS and survive reflashing.
- **Serial reset trap:** this USB port resets the chip when RTS is high while DTR is low.
  pyserial's defaults keep both lines high. Don't set `dtr = False` before opening the port:
  pyserial lowers DTR before RTS, and the chip resets.
- The USB receive buffer is raised to 4 KB (`Serial.setRxBufferSize`). The 256-byte default
  cut off status lines.

## Protocol

Each request is one line, and each reply is one line: `{"ok":true,...}` or
`{"ok":false,"error":"..."}`. The host skips lines that aren't JSON, such as the ROM boot log.

| Request | Effect |
|---|---|
| `{"cmd":"hello"}` | Replies with `device` (`busytag-esp32`), `fw`, `board`, `width`, `height`, `rotation`, `brightness`, `uptime_ms` |
| `{"cmd":"status","top":"attention","rows":[[label,state,detail,"RRGGBB"],…],"led":{…}}` | Draws the status screen (header, most urgent agent, agent list) and sets the LED |
| `{"cmd":"idle"}` | Draws the idle screen and turns the LED off |
| `{"cmd":"led","effect":"solid\|pulse\|off","color":"RRGGBB","low":"RRGGBB"}` | Sets the LED; `pulse` fades between `low` and `color` (1.6 s cycle) |
| `{"cmd":"brightness","value":1-100}` | Sets the backlight (omit `value` to read) |
| `{"cmd":"rotate","value":0-3}` | Sets the rotation and redraws (omit `value` to read) |
| `{"cmd":"fill","color":"RRGGBB"}` | Fills the screen with one color |
| `{"cmd":"screen"}` | Replies with `screen` (the last screen command, e.g. `{"cmd":"fill","color":"003366"}`; a status screen is only `{"cmd":"status"}`) and `led` (`effect`, `color`, `low`). Added in 0.2.0 |

The fonts are ASCII-only, and the host converts text to ASCII first.

## Restoring the factory demo

The original flash was backed up to `device-backup/esp32-c6-lcd-factory/flash-8mb.bin`.
The backup is git-ignored, so it exists only on the machine that made it. To restore it:

```bash
uvx esptool --port /dev/cu.usbmodem101 write-flash 0 device-backup/esp32-c6-lcd-factory/flash-8mb.bin
```
