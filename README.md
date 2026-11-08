# busytag

Command-line control for a Busy Tag USB display (firmware 2.x).

```bash
just install                              # puts `busytag` on PATH
busytag info
busytag image list                        # * marks the image on screen
busytag image upload photo.jpg --show     # static images are fitted to 240x280 PNG
busytag image show Busy_uwkmkuod.png
busytag image delete old.gif              # switches away first if it's on screen
busytag image fill purple                 # solid screen color
busytag led color red --leds 1,4,7        # names or RRGGBB; LEDs 1-7, 'all', or a mask
busytag led pattern "Red Pulses" -r 3     # built-in pattern by name or ID; 255 = forever
busytag led patterns | stop | off
busytag brightness 60
busytag raw 'AT+GFV'                      # debug: send any AT command
```

The port is auto-detected; override with `--port` or `BUSYTAG_PORT`.
Quit the Busy Tag desktop app first: only one program can use the port.

## Agent status

Agents report their state; the screen shows the most urgent one, plus a list of every
active agent. When the last agent finishes, your own image, LED color and pattern come back.

| State | Screen | LEDs |
|-------|--------|------|
| `attention` | orange "NEEDS YOU" + reason | pulsing orange |
| `error` | red "ERROR" | solid red |
| `done` | green "DONE" | solid green |
| `working` | blue "WORKING" | solid blue |
| `idle` / `clear` | not shown / removed | — |

```bash
busytag status attention --agent build --label "CI build" --detail "tests failed"
busytag status clear --agent build
busytag agents            # who is reporting what
busytag agents --reset    # forget everyone, restore your screen
```

State lives in `~/.cache/busytag/` (`BUSYTAG_STATE_DIR` to override). Device errors from
hooks are logged to `hook.log` there. Agents silent for 12 hours are dropped.

### Claude Code

Merge `hooks/claude-settings.json` into `~/.claude/settings.json`. Every event runs
`busytag hook claude` with `"async": true`, so Claude never waits for the display.
Each session shows as its project folder name.

| Hook event | Status |
|------------|--------|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure` | working |
| `PermissionRequest`, `Notification` (permission / input needed) | attention |
| `Stop` | done |
| `StopFailure` | error |
| `SessionEnd` | removed |
