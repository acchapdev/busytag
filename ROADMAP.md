# Roadmap

Where the project stands and what is left. Update the checkpoint when you stop working.

## Checkpoint: 2026-11-23

**In progress: Cheap Yellow Display (touch) on branch `feat-esp32-cyd`**, worktree
`~/projects/busytag.feat-esp32-cyd` (also linked from `~/projects/esp32/cyd/busytag-cyd`).
Nothing is committed yet; 166 tests pass. `main` is as of 2026-11-08 (everything merged and
pushed to https://github.com/acchapdev/busytag).

What's built (see `firmware/esp32-cyd/README.md` and the CYD section of `CLAUDE.md`):

- Firmware 0.1.0 for the ESP32-2432S028 (ILI9341 + XPT2046 touch), flashed and running on
  the board at `/dev/cu.wchusbserial110`. Agent list, detail view, settings (brightness, LED,
  flip, sleep) all work on the board, checked by tapping.
- Host: CH340 ports are probed with `hello`; rows carry agent ID, age and a jump flag;
  the Claude hook records `REX_SESSION`/`REX_BLOCK`; `busytag watch` polls the board's
  `events` every loop and runs `jump.go` (Rex session.select, focus, `open -a Rex`).

Where it stopped:

1. **Re-test Jump on the device.** The first test (12:46) failed with `block target ... not
   found`: `rex block inspect` only searches the caller's session unless given `-s`. Fixed
   in `jump.py` (passes `-s session`) with a test, but not yet re-tested by tapping. Tap an
   agent from *another* Rex session, then `Jump to it`; Rex should switch within ~2 s.
2. `busytag watch` must be running for Jump. The LaunchAgent isn't loaded on this laptop;
   it was run by hand from a Claude session. Decide whether to `busytag setup` / load it.
3. The installed `busytag` is an editable install of **the worktree** (all hooks run branch
   code). After merging, run `just install` from `~/projects/busytag` to point it back.
4. Unexplained: the board reset a few times right after the first flash; not reproduced
   (40 port opens, no resets). `watch` redraws a reset board via the `fresh` flag.
5. Then: `wt step commit`, `git push -u origin HEAD`, `gh pr create` (gh account
   `acchapdev`); after the merge, `wt remove` and repoint the `busytag-cyd` link.

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
- Done timeout: `done` agents leave the display after `[status] done_timeout` minutes
  (default 60), checked every minute by `busytag watch`. Fixes sessions closed without exiting.
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
