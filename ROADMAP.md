# Roadmap

Where the project stands and what is left. Update the checkpoint when you stop working.

## Checkpoint: 2026-11-08

Everything is merged to `main` and pushed to https://github.com/acchapdev/busytag (public).
No open branches or worktrees. 110 tests pass (`just test`).

**Done**

- Device on firmware 2.0 (upgraded from 1.0; 2.x is the ceiling for this hardware). See `DEVICE.md`.
- `busytag` CLI: `info`, `brightness`, `files`, `raw`, `image list|show|upload|delete|fill`,
  `led color|off|brightness|patterns|pattern|stop`, `config`.
- Agent status board (`status`, `agents`, `hook`): most urgent agent on screen, LED color per
  agent type (`~/.config/busytag/config.toml`), your own image/LEDs/pattern restored when idle.
- Claude Code hooks: installed in `~/.claude/settings.json` on this laptop and working.
- OpenCode 2 plugin: installed on this laptop as a symlink to the checkout (`just install-opencode`),
  tested through the background service.
- ESP32 display (PR #1): a Waveshare ESP32-C6-LCD-1.47 running busytag's firmware
  (`firmware/esp32-c6-lcd/`) shows the status board in landscape, with ~0.14 s updates.
  `busytag` auto-detects it (a Busy Tag wins if both are plugged in). Verified on the board:
  `info`, `status`, `agents`, `rotate` (rotation 3 is upright in the case), the layout, and
  the LED color order (RGB).
- ESP32 home screen: like the Busy Tag, the ESP32 puts back the screen (idle or a fill color)
  and LED it showed before agent status, using the `screen` command in firmware 0.2.0
  (flashed and verified on the board 2026-11-09).
- Plug-in refresh: `busytag watch` (LaunchAgent installed by `busytag setup`) redraws the
  status screen when a display is plugged in, instead of waiting for the next agent event.
- TUI (`busytag tui`): live agent list (most urgent first, with IDs), clear one agent or all,
  and display controls: image picker, screen fill, LED color, built-in patterns, LEDs off,
  screen and LED brightness. Checked headless against the Busy Tag.
- Desktop apps checked 2026-11-09: the Claude desktop **Code tab** runs the hooks, and
  **OpenCode desktop** reports through the service plugin with the right folder label.
  Desktop chat and Cowork (a VM) can't run host hooks; not needed.
- Installer: `curl -fsSL https://raw.githubusercontent.com/acchapdev/busytag/main/install.sh | bash`,
  plus `busytag setup [--only claude|opencode] [--remove]`. Tested end to end from GitHub in a sandbox.

**This laptop's setup**

- `busytag` is an editable `uv tool` install of `~/projects/busytag` (`just install`), so code
  changes take effect immediately. Running `install.sh` here would replace it with a copy.
- LED brightness is set to 10%.
- The ESP32 display is flashed and plugged in; its factory flash is backed up (git-ignored) in
  `device-backup/esp32-c6-lcd-factory/`.
- Git pushes go over HTTPS with `gh` credentials (`gh auth setup-git`); the active `gh` account
  must be `acchapdev`. The SSH key signs in as `acchapm1`, which can't push to this repo.

## Next up

1. **TUI, next steps:** image upload/delete from the dashboard, and an agent detail view.
2. **Watch an interactive OpenCode permission prompt on the device.** The attention state is
   tested only with captured events (non-interactive runs reject prompts instantly). Open
   OpenCode with `"permission": {"bash": "ask"}`, trigger a command, and check the blue pulse.
3. **More agents** (e.g. Codex, Gemini CLI, Cursor): add `[agents.<name>]` colors in the
   default config, an event mapping in `hooks.py`, and a `setup` integration.
4. **CI**: a GitHub Actions workflow running `uv run pytest` on push.
5. **Hardware tests**: CLAUDE.md mentions `@pytest.mark.device` tests, but none exist yet.
6. **Release/versioning**: still `0.1.0`, no tags. `BUSYTAG_REF` in `install.sh` can pin a tag.

## Future ideas

- **Bluetooth for the ESP32 display**, so it works without a USB cable. The ESP32-C6 has BLE.
- **Touch input**: there is an ESP32 1.47" board with a touch screen. What touch should do
  is still open; options to explore: tap to dismiss attention (clear the top agent), swipe
  through agents, tap an agent for its detail, or long-press to clear all.
- **Shorter timeout for closed sessions**: closing a terminal without exiting the agent leaves
  it as `done` for 12 h (and only drops then on the next report). A configurable timeout for
  `done` agents would fix it; the TUI's clear key (`x`) is the manual way meanwhile.

## Open decisions

- **Email in public history**: all commits and `pyproject.toml` carry `acchapm1@asu.edu`.
  Changing it means rewriting history and force-pushing.
- **Lost GIF**: `5ee6c27d6de3657abdaf.gif` (846 KB) didn't survive the firmware upgrade. It is
  in `device-backup/fw1.0-20261108/` (git-ignored) and could be re-uploaded with `busytag image upload`.

## Known limitations

- Claude Code fires no hook when you approve a permission prompt, so "attention" stays until
  the next tool event, prompt, or Stop.
- OpenCode's event payloads are undocumented; the mapping was captured from 2.2.5. Recheck
  after OpenCode upgrades. A changed plugin needs `opencode service restart`.
- A screen update takes about 1 s (upload + show). Hooks are async, so agents don't wait.
- The serial port is exclusive: quit the Busy Tag desktop app while using busytag.
- Linux support in `install.sh` is untested on a real Linux machine.
