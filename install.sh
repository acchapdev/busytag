#!/usr/bin/env bash
# Install busytag and its agent integrations (Claude Code hooks, OpenCode plugin).
#
#   curl -fsSL https://raw.githubusercontent.com/acchapdev/busytag/main/install.sh | bash
#
# Options go after `bash -s --`:
#   ... | bash -s -- --only claude     # just one integration (claude or opencode)
#   ... | bash -s -- --uninstall       # remove the integrations and the busytag command
#
# Environment:
#   BUSYTAG_SOURCE  what to install (default: the GitHub repo); any `uv tool install`
#                   source works, e.g. a local checkout: BUSYTAG_SOURCE=~/src/busytag
#   BUSYTAG_REF     branch or tag of the GitHub repo (default: main)
#
# Safe to run again: it upgrades busytag and replaces its own hook entries.

set -euo pipefail

REPO_URL='https://github.com/acchapdev/busytag'
REF="${BUSYTAG_REF:-main}"
SOURCE="${BUSYTAG_SOURCE:-git+${REPO_URL}@${REF}}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

case "$(uname -s)" in
  Darwin | Linux) ;;
  *) die "busytag supports macOS and Linux, not $(uname -s)" ;;
esac

uninstall=false
setup_args=()
for arg in "$@"; do
  if [ "$arg" = '--uninstall' ]; then uninstall=true; else setup_args+=("$arg"); fi
done

ORIGINAL_PATH="$PATH"
# Where uv's installer puts uv itself
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if $uninstall; then
  command -v uv >/dev/null 2>&1 && PATH="$(uv tool dir --bin):$PATH"
  if command -v busytag >/dev/null 2>&1; then
    say 'Removing agent integrations'
    busytag setup --remove
  fi
  if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^busytag '; then
    say 'Removing the busytag command'
    uv tool uninstall busytag
  fi
  say 'Done. Your busytag config (~/.config/busytag) and state (~/.cache/busytag) were kept.'
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  say 'Installing uv (Python package manager, https://docs.astral.sh/uv/)'
  command -v curl >/dev/null 2>&1 || die 'curl is required to install uv'
  curl -LsSf https://astral.sh/uv/install.sh | sh
  command -v uv >/dev/null 2>&1 || die 'uv was installed but is not on PATH; open a new shell and run this again'
fi

# Where uv puts tool commands (~/.local/bin unless XDG_BIN_HOME or UV_TOOL_BIN_DIR say otherwise)
BIN_DIR="$(uv tool dir --bin)"
export PATH="$BIN_DIR:$PATH"

say "Installing busytag from ${SOURCE}"
# --force replaces an existing install (including an editable development one)
uv tool install --force --reinstall "$SOURCE"
BUSYTAG="$BIN_DIR/busytag"
[ -x "$BUSYTAG" ] || die "busytag was installed but is not in $BIN_DIR"

say 'Setting up agent integrations'
"$BUSYTAG" setup "${setup_args[@]+"${setup_args[@]}"}"

if [ "$(uname -s)" = Linux ] && ! id -nG | tr ' ' '\n' | grep -qx dialout; then
  warn "to use the serial port, add yourself to the dialout group and log in again:"
  warn "  sudo usermod -aG dialout \"\$USER\""
fi

case ":$ORIGINAL_PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH; run 'uv tool update-shell' and open a new shell" ;;
esac

say 'Done. Try: busytag info'
echo '    Close the Busy Tag desktop app first: only one program can use the device at a time.'
