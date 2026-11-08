# Default: list available recipes
default:
  @just --list

# Run the unit tests (no device needed)
test:
  uv run pytest -q

# Show device info
info:
  uv run busytag info

# Install the busytag command on PATH (editable, follows code changes)
install:
  uv tool install --editable . --force

# Link the OpenCode 2 plugin into ~/.config/opencode/plugins (follows code changes)
install-opencode:
  mkdir -p ~/.config/opencode/plugins
  ln -sf "{{justfile_directory()}}/plugins/opencode/busytag.ts" ~/.config/opencode/plugins/busytag.ts
  @echo "Linked. OpenCode reloads plugins automatically; if not, run: opencode service restart"
