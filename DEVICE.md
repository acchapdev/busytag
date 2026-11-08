# Busy Tag — Connected Device

> Last probed: 2026-11-08 over USB-C on macOS (Darwin 25.6.0), after upgrading firmware 1.0 → 2.0
> Project links: https://busy-tag.github.io · https://github.com/busy-tag
> Protocol reference for this firmware: https://busy-tag.github.io/hardware/at-commands-v2

## Identity

| Field | Value | Source |
|-------|-------|--------|
| Product | BUSY TAG (original hardware) | USB descriptor |
| Manufacturer | SIA BUSY TAG (was "GREYNUT LTD" on fw 1.0) | USB descriptor, `AT+GMN` |
| Device name / hostname | `busytag-EDC770` | `AT+GDN` |
| Device ID / serial | `9C139EEDC770` (chip MAC) | USB serial, `AT+GID` |
| Firmware | **2.0**, built Mar 15 2026 05:29:41 | `AT+GFV`, `AT+GESPCT` |
| Hardware version | 1.0 | `AT+GHV` |
| Bootloader | 1.0 | `AT+GBLV` |
| ESP-IDF | v5.1.2-dirty | `AT+GESPV` |
| Chip | ESP32-S3 rev 2, 2 cores, Wi-Fi + BLE radio | `AT+GCHI` |
| Temperature | 42.7 °C at probe time | `AT+GTEMP` |

The chip has a Wi-Fi radio, but firmware 2.x doesn't use it. Wi-Fi and the HTTP API come
only with firmware 3.x, which runs only on Busy Tag 2 hardware.

## Firmware history

| Version | Built | Notes |
|---------|-------|-------|
| 1.0 | May 16 2024 | USB drive (FAT12) + serial; replied `OK` to unknown commands. Files backed up in `device-backup/fw1.0-20261108/` |
| 2.0 | Mar 15 2026 | Installed 2026-11-08 with Busy Tag app 1.7.4. Serial only, no USB drive. **All files were kept** |

## USB

| Field | Value |
|-------|-------|
| Vendor ID | `0x303a` (Espressif) |
| Product ID | `0x81df` |
| bcdDevice | `0x0200` (was `0x0100` on fw 1.0) |
| Link speed | 12 Mb/s (USB Full Speed) |
| Interfaces | CDC serial only. The USB drive is gone since fw 2.0 |

## Serial interface

- Port: `/dev/cu.usbmodem9C139EEDC7701`. Use `cu.*` for opening, not `tty.*`.
- 460800 baud as documented (USB CDC ignores the rate). 8N1, commands end with `\r\n`.
- Replies: zero or more `+PREFIX:data` lines. Multi-line replies end with `OK`.
  Single-value replies (`+DN:…`) have no `OK` after them. Unknown commands return `ERROR:1`.
- Only one process can open the port at a time. Quit the Busy Tag app before using it.

### Verified on fw 2.0

| Command | Response |
|---------|----------|
| `AT` | `OK` |
| `AT+XYZZY` (unknown) | `ERROR:1` |
| `AT+GDN` / `AT+GMN` / `AT+GID` | `+DN:busytag-EDC770` / `+MN:SIA BUSY TAG` / `+ID:9C139EEDC770` |
| `AT+GFV` / `AT+GHV` / `AT+GBLV` | `+FV:2.0` / `+HV:1.0` / `+BLV:1.0` |
| `AT+GESPV` / `AT+GESPCT` | `+ESPV:v5.1.2-dirty` / `+ESPCT:Mar 15 2026 05:29:41` |
| `AT+GTEMP` | `+TEMP:42.7` |
| `AT+GCHI` | `+CHI:ESP32-S3,2,2,WiFi,BLE` |
| `AT+GTSS` / `AT+GFSS` | `+TSS:3080192` / `+FSS:942080` |
| `AT+GFL` | `+FL:<name>,<ext>,<size>` per file, then `OK` |
| `AT+GPL` | `+PL:<name>,<size>` per image, then `OK` |
| `AT+SP?` | `+SP:plugin1.png` |
| `AT+DB?` | `+DB:100` |
| `AT+SC?` | `+SC:127,0000FE` |
| `AT+CP?` | `+CP:127,1291AF,100,0` / `+CP:127,FF0000,100,0`, then `OK` |
| `AT+PP?` | `+PP:1,3` (pattern playing, repeat count 3) |
| `AT+GDPL` | `+DPL:<id>,<name>` × 29, then `OK` |
| `AT+DC?` | `+DC:FFFFFF` (display fill color) |
| `AT+GLEC` | `+LEC:1` |
| `AT+GLRR0` | `+LRR0:3` (reset reason, core 0) |

These return `ERROR:1` on 2.0, meaning they're 3.x only: `AT+GUSBS`, `AT+DD?`, `AT+DDC?`,
`AT+SM?`, `AT+TB?`, `AT+WM?`.

Set commands verified on the device: `AT+SP=`, `AT+DC=`, `AT+DB=`, `AT+SC=`, `AT+DP=`
(loads the pattern; `AT+PP=1,<n>` plays it), `AT+CPD=`, `AT+UF=`, `AT+DF=` (`ERROR:0` if the
image is on screen). `AT+CP=<n>` with the `>` prompt drops steps; use `AT+CPD` instead.

### Built-in LED patterns (`AT+DP=<id>`)

| ID | Name | ID | Name | ID | Name |
|----|------|----|------|----|------|
| 0 | Default | 10 | Red Running | 20 | Yellow Pulses |
| 1 | Police 1 | 11 | Green Running | 21 | Magenta Pulses |
| 2 | Police 2 | 12 | Blue Running | 22 | Cyan Pulses |
| 3 | Red Flashes | 13 | Yellow Running | 23 | White Pulses |
| 4 | Green Flashes | 14 | Magenta Running | 24 | Rainbow |
| 5 | Blue Flashes | 15 | Cyan Running | 25 | Fire |
| 6 | Yellow Flashes | 16 | White Running | 26 | Sparkle |
| 7 | Magenta Flashes | 17 | Red Pulses | 27 | Wave |
| 8 | Cyan Flashes | 18 | Green Pulses | 28 | Alert |
| 9 | White Flashes | 19 | Blue Pulses | | |

Firmware 2.0 has 29 patterns. The docs list only 25 (0–24): 25–28 (Fire, Sparkle, Wave,
Alert) are new.

## Display and LEDs

- Screen: 240 × 280 px, PNG or animated GIF (GIFs up to ~1 MB).
- LEDs: 7. `led_bits` is a bitmask (`1` = LED1 … `64` = LED7, `127` = all). Colors are `RRGGBB`.

## Storage

- Total 3,080,192 bytes. Free **942,080 bytes (~920 KB)**, up from ~110 KB on fw 1.0.
  Most of the gain is the 846 KB `5ee6c27d6de3657abdaf.gif`, which isn't on the device
  anymore (110 KB + 846 KB − 16 KB for the new `def.png` ≈ 940 KB).
- Upload with `AT+UF=<file>,<size>`: the device replies `>`, then you send the raw bytes.
- The upgrade added `def.png` (16 KB), probably the default image.

| File | Size |
|------|------|
| `readme.txt` | 120 B |
| `config.json` | 360 B |
| `wifi_config.json` | 33 B (SSID is still the placeholder; contains a password field, don't copy it into docs) |
| `def.png` | 16 KB (new) |
| `plugin1.png` | 15 KB, **currently shown** |
| `Hello_rn15t9y5.gif` | 544 KB |
| `Tomato_focused_8nix3yzf.png` | 2.7 KB |
| `Busy_uwkmkuod.png` | 1.9 KB |
| `Let's_talk_7zgg4pkr.png` | 2.1 KB |
| `Short_break_oomzmp2x.png` | 2.3 KB |
| `b2204d4fbc65daeac711.png` | 62 KB |
| `0730ffea6de4b0ed2188.gif` | 434 KB |
| `5ee6c27d6de3657abdaf.gif` | 846 KB (in `AT+GPL` on 1.0; **missing from the 2.0 file list**, but still in the backup) |
| `6c9da73bb15bbdbb0697.gif` | 318 KB |
| `48d73a09c3eb0e2f408f.gif` | 145 KB |
| `499c5968ee0a424bbd2d.gif` | 322 KB |
| `e5d71f3e125140af1c4a.gif` | 216 KB |

## Quick probe

```bash
uv run --with pyserial python - <<'EOF'
import serial, time
s = serial.Serial('/dev/cu.usbmodem9C139EEDC7701', 460800, timeout=0.5)
for c in ['AT+GFV', 'AT+SP?', 'AT+GFSS']:
    s.write((c + '\r\n').encode()); time.sleep(0.3)
    print(s.read(1024).decode().strip())
EOF
```
