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
  ln -sf "{{justfile_directory()}}/src/busytag/integrations/opencode.ts" ~/.config/opencode/plugins/busytag.ts
  @echo "Linked. Load it with: opencode service restart"

# Build the ESP32 display firmware
fw-build:
  cd firmware/esp32-c6-lcd && uvx --from platformio pio run

# Build and flash the ESP32 display firmware (PORT overrides auto-detection)
fw-flash PORT='':
  cd firmware/esp32-c6-lcd && uvx --from platformio pio run -t upload {{ if PORT != '' { '--upload-port ' + PORT } else { '' } }}

# Watch the ESP32 display's serial output (Ctrl-C to quit; busytag can't use the port meanwhile)
fw-monitor:
  cd firmware/esp32-c6-lcd && uvx --from platformio pio device monitor
