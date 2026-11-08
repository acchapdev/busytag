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
