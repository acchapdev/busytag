# Roadmap

Where the project stands and what is left. Update the checkpoint when you stop working.

## Checkpoint: 2026-11-08 (ESP32 display)

Work in progress on branch `feat-esp32-backend` (worktree `~/projects/busytag.feat-esp32-backend`),
not merged yet. 110 tests pass. Adds the Waveshare ESP32-C6-LCD-1.47 as a second display:
firmware in `firmware/esp32-c6-lcd/` (flashed to the board and working), `esp32.py`,
`open_device()` auto-detection, and a device-drawn path in `status.push`. Verified on the board:
`info`, `status`, `agents`, `rotate` (rotation 3 is upright in the case), and update time (0.14 s).
Also verified: the screen layout and the LED color order (RGB, fixed after red showed as green).
The editable `busytag` on PATH still points at the main checkout, so hooks use the Busy Tag code
until this branch is merged.

Before this branch, everything was merged to `main` and pushed to
https://github.com/acchapdev/busytag (public).

**Done**

- Device on firmware 2.0 (upgraded from 1.0; 2.x is the ceiling for this hardware). See `DEVICE.md`.
- `busytag` CLI: `info`, `brightness`, `files`, `raw`, `image list|show|upload|delete|fill`,
  `led color|off|brightness|patterns|pattern|stop`, `config`.
- Agent status board (`status`, `agents`, `hook`): most urgent agent on screen, LED color per
  agent type (`~/.config/busytag/config.toml`), your own image/LEDs/pattern restored when idle.
- Claude Code hooks: installed in `~/.claude/settings.json` on this laptop and working.
- OpenCode 2 plugin: installed on this laptop as a symlink to the checkout (`just install-opencode`),
  tested through the background service.
- Installer: `curl -fsSL https://raw.githubusercontent.com/acchapdev/busytag/main/install.sh | bash`,
  plus `busytag setup [--only claude|opencode] [--remove]`. Tested end to end from GitHub in a sandbox.

**This laptop's setup**

- `busytag` is an editable `uv tool` install of `~/projects/busytag` (`just install`), so code
  changes take effect immediately. Running `install.sh` here would replace it with a copy.
- LED brightness is set to 10%.
- Git pushes go over HTTPS with `gh` credentials (`gh auth setup-git`); the active `gh` account
  must be `acchapdev`. The SSH key signs in as `acchapm1`, which can't push to this repo.

## Next up

1. **TUI** (`textual`): the original idea. A live dashboard of agents and device controls
   (image picker, LED color/pattern, brightness). Not started; `src/busytag/tui.py` is planned.
2. **Watch an interactive OpenCode permission prompt on the device.** The attention state is
   tested only with captured events (non-interactive runs reject prompts instantly). Open
   OpenCode with `"permission": {"bash": "ask"}`, trigger a command, and check the blue pulse.
3. **More agents** (e.g. Codex, Gemini CLI, Cursor): add `[agents.<name>]` colors in the
   default config, an event mapping in `hooks.py`, and a `setup` integration.
4. **CI**: a GitHub Actions workflow running `uv run pytest` on push.
5. **Hardware tests**: CLAUDE.md mentions `@pytest.mark.device` tests, but none exist yet.
6. **Release/versioning**: still `0.1.0`, no tags. `BUSYTAG_REF` in `install.sh` can pin a tag.

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
