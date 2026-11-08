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
busytag led brightness 40               # LED brightness %, saved in the config
busytag brightness 60                     # display brightness
busytag config                            # show the config file
busytag raw 'AT+GFV'                      # debug: send any AT command
```

The port is auto-detected; override with `--port` or `BUSYTAG_PORT`.
Quit the Busy Tag desktop app first: only one program can use the port.

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

### OpenCode

`just install-opencode` links `plugins/opencode/busytag.ts` into
`~/.config/opencode/plugins/`. It is an OpenCode 2 plugin (tested on 2.2.5) that forwards
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
