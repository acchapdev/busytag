"""User configuration: ~/.config/busytag/config.toml (BUSYTAG_CONFIG overrides the path).

The file is created with defaults on first use. tomlkit keeps the user's comments and
layout when busytag writes a value back (e.g. `busytag led brightness 40`).
"""

import os
from pathlib import Path

import tomlkit

from busytag.colors import parse_color

DEFAULT_CONFIG = '''\
# busytag configuration

[leds]
# LED brightness in percent (1-100). The device has no LED brightness setting,
# so busytag scales every LED color it sends.
brightness = 100

[status]
# Minutes a finished ("done") agent stays on the display. Closing a terminal without
# exiting the agent sends no end event, so this is what clears it. 0 = keep it until
# the agent is silent for 12 hours, like the other states.
done_timeout = 60

# LED color for each agent type, so you can tell agents apart at a glance.
# An agent's type is the part of its ID before ':' (Claude Code sessions report
# as "claude:<session-id>"), or the whole ID when it has no ':'.
# Colors are RRGGBB hex or a name (red, orange, blue, ...).
[agents.claude]
color = "FF6000"   # orange

[agents.opencode]
color = "0060FF"   # blue

# Any agent type not listed above
[agents.default]
color = "FFFFFF"
'''


def config_path():
  return Path(os.environ.get('BUSYTAG_CONFIG', Path.home() / '.config' / 'busytag' / 'config.toml'))


def load_document():
  path = config_path()
  if not path.exists():
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG)
  return tomlkit.parse(path.read_text())


def load():
  """Return {'brightness': int, 'done_timeout': seconds or None, 'agent_colors': {kind: RRGGBB}}
  with defaults filled in."""
  defaults = tomlkit.parse(DEFAULT_CONFIG).unwrap()
  try:
    data = load_document().unwrap()
  except (OSError, tomlkit.exceptions.ParseError):
    # A broken config must never break hooks; fall back to defaults
    data = defaults
  brightness = data.get('leds', {}).get('brightness', 100)
  agents = {**defaults['agents'], **data.get('agents', {})}
  colors = {}
  for kind, settings in agents.items():
    try:
      colors[kind] = parse_color(str(settings.get('color', 'FFFFFF')))
    except ValueError:
      colors[kind] = 'FFFFFF'
  try:
    done_minutes = float(data.get('status', {}).get('done_timeout', 60))
  except (TypeError, ValueError):
    done_minutes = 60
  return {
    'brightness': max(1, min(100, int(brightness))),
    'done_timeout': done_minutes * 60 if done_minutes > 0 else None,
    'agent_colors': colors,
  }


def agent_kind(agent):
  return agent.split(':', 1)[0]


def agent_color(config, agent):
  colors = config['agent_colors']
  return colors.get(agent_kind(agent), colors.get('default', 'FFFFFF'))


def set_brightness(level):
  document = load_document()
  document.setdefault('leds', tomlkit.table())['brightness'] = level
  config_path().write_text(tomlkit.dumps(document))
