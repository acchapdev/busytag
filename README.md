# busytag

Command-line control for a Busy Tag USB display (firmware 2.x), and a status board that
shows when your AI agents (Claude Code, OpenCode) are working, done, or need you. The
status board also runs on a Waveshare ESP32-C6-LCD-1.47 with busytag's own firmware
(see [ESP32 display](#esp32-display)).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/acchapdev/busytag/main/install.sh | bash
```

This installs [uv](https://docs.astral.sh/uv/) if needed, installs the `busytag` command,
and runs `busytag setup`, which installs the agent integrations it finds:

- **Claude Code:** adds an async `busytag hook claude` hook to `~/.claude/settings.json`
  (backed up first; your other settings and hooks are kept). Applies to new sessions.
- **OpenCode 2:** installs the plugin to `~/.config/opencode/plugins/busytag.ts`. Run
  `opencode service restart` to load it.
- **Plug-in refresh (macOS):** installs a LaunchAgent that runs `busytag watch`, which
  redraws the status screen within a few seconds of a display being plugged in (otherwise
  the screen waits for the next agent event). Log: `~/.cache/busytag/watch.log`.

Run it again to upgrade. Options go after `bash -s --`: `--only claude` or
`--only opencode` or `--only watch` for one integration, `--uninstall` to remove everything (your config
and state are kept). `busytag setup [--only X] [--remove]` does the integration part alone.
macOS and Linux; on Linux you must be in the `dialout` group to use the serial port.

From a checkout: `just install` (editable install that follows code changes), then
`busytag setup`. `just install-opencode` links the plugin instead of copying it.

## Use

`busytag tui` opens a dashboard: the agents reporting (most urgent first, refreshed every
second) and the display, with keys for clearing an agent (`x`) or all (`R`), showing an
image (`i`), filling the screen (`f`), LED color (`c`), built-in patterns (`p`), LEDs off
(`o`), and brightness (`[` `]` screen, `-` `+` LEDs).

```bash
busytag info
busytag image list                        # * marks the image on screen
busytag image upload photo.jpg --show     # static images are fitted to 240x280 PNG
busytag image show Busy_uwkmkuod.png
busytag image delete old.gif              # switches away first if it's on screen
busytag image fill purple                 # solid screen color
busytag led color red --leds 1,4,7        # names or RRGGBB; LEDs 1-7, 'all', or a mask
busytag led pattern "Red Pulses" -r 3     # built-in pattern by name or ID; 255 = forever
busytag led patterns | stop | off
busytag led brightness 40               # LED brightness %, saved in the config
busytag brightness 60                     # display brightness
busytag config                            # show the config file
busytag raw 'AT+GFV'                      # debug: send any AT command
```

The port is auto-detected; override with `--port` or `BUSYTAG_PORT`.
Quit the Busy Tag desktop app first: only one program can use the port.

## ESP32 display

A [Waveshare ESP32-C6-LCD-1.47](https://www.waveshare.com/wiki/ESP32-C6-LCD-1.47) (1.47"
172x320 screen, one RGB LED) can stand in for the Busy Tag. Its firmware, in
`firmware/esp32-c6-lcd/`, draws the status screen itself in landscape, so updates take
about 0.1 s. Flash it once from a checkout (PlatformIO runs through `uvx`):

```bash
just fw-flash            # build and flash; the board must be the only ESP32 plugged in
busytag info             # should say busytag-esp32
busytag rotate 1         # flip 180 degrees if it is upside down in your case (saved)
```

`busytag` finds the display on its own: a Busy Tag wins if both are plugged in, and
`--port` / `BUSYTAG_PORT` picks one. The ESP32 supports `status`, `agents`, `hook`, `info`,
`brightness`, `rotate`, `image fill`, `led color|off|stop|brightness` and `raw` (a JSON
line such as `'{"cmd":"hello"}'`). It has no image storage or LED patterns. See
`firmware/esp32-c6-lcd/README.md` for the protocol and how to restore the factory demo.

## Agent status

Agents report their state; the screen shows the most urgent one, plus a list of every
active agent. When the last agent finishes, your own image, LED color and pattern come back.

The LED **color** says which kind of agent it is; the LED **effect** says its state.

| State | Screen | LEDs |
|-------|--------|------|
| `attention` | orange "NEEDS YOU" + reason | pulsing, in the agent's color |
| `error` | red "ERROR" | solid red (any agent) |
| `done` | green "DONE" | solid, agent's color |
| `working` | blue "WORKING" | dim (25%), agent's color |
| `idle` / `clear` | not shown / removed | — |

### Agent colors and LED brightness

`~/.config/busytag/config.toml` (created on first use; `BUSYTAG_CONFIG` to override):

```toml
[leds]
brightness = 100          # also set with: busytag led brightness 40

[agents.claude]
color = "FF6000"          # orange
[agents.opencode]
color = "0060FF"          # blue
[agents.default]
color = "FFFFFF"          # any type not listed
```

An agent's type is the part of its ID before `:`. Claude Code and OpenCode sessions report as
`claude:<session>` and `opencode:<session>`; report other agents as `<type>:<id>`, e.g.
`busytag status working -a opencode:ses42 -l api-server`. Add a type by adding an
`[agents.<type>]` table. The device has no LED brightness setting, so busytag scales
every LED color it sends (solid colors, patterns and status LEDs).

```bash
busytag status attention --agent build --label "CI build" --detail "tests failed"
busytag status clear --agent build
busytag agents            # who is reporting what
busytag agents --reset    # forget everyone, restore your screen
```

State lives in `~/.cache/busytag/` (`BUSYTAG_STATE_DIR` to override). Device errors from
hooks are logged to `hook.log` there. Agents silent for 12 hours are dropped.

The screen changes only when an agent reports. If the display was unplugged meanwhile,
`busytag watch` (the plug-in refresh LaunchAgent) redraws it when it is plugged back in.

### Claude Code

`busytag setup` adds the hooks to `~/.claude/settings.json`. Every event runs
`busytag hook claude` with `"async": true`, so Claude never waits for the display.
Each session shows as its project folder name.

| Hook event | Status |
|------------|--------|
| `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure` | working |
| `PermissionRequest`, `Notification` (permission / input needed) | attention |
| `Stop` | done |
| `StopFailure` | error |
| `SessionEnd` | removed |

### OpenCode

`busytag setup` installs `src/busytag/integrations/opencode.ts` as
`~/.config/opencode/plugins/busytag.ts`; run `opencode service restart` afterwards, because
the running service doesn't pick up new or changed plugins. It is an OpenCode 2 plugin (tested on 2.2.5) that forwards
session events to `busytag hook opencode` in the background. Each session shows as its
project folder name, with the `[agents.opencode]` LED color.

| OpenCode event | Status |
|----------------|--------|
| `session.execution.started`, `permission.replied`, `form.replied`/`cancelled` | working |
| `permission.asked`, `form.created` (a question for you) | attention |
| `session.execution.succeeded` | done |
| `session.execution.failed` | error |
| `session.execution.interrupted` (you pressed Esc) | idle |
| `session.deleted` | removed |

Subagent sessions don't show up on their own: their permission prompts and questions are
shown under the session that started them. The plugin looks for `~/.local/bin/busytag`
(where `just install` puts it); set `BUSYTAG_BIN` to use another one.
