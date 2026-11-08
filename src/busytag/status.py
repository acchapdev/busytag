"""Agent status board: many agents report state, the device shows the most urgent.

There is no daemon. Each update takes an exclusive lock on the state file, records the
agent's state, and pushes to the device only when what should be on screen has changed.
The lock also serializes device access between concurrent hook processes.
"""

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

# Lowest to highest urgency; the most urgent agent decides the LEDs and headline
STATES = ['idle', 'working', 'done', 'error', 'attention']
PRIORITY = {state: rank for rank, state in enumerate(STATES)}
STALE_SECONDS = 12 * 3600

# Two names because the device refuses to overwrite the image it is showing
STATUS_FILES = ['bt_status0.png', 'bt_status1.png']

# LED looks per state: ('solid', color) or ('pattern', steps). Pulse steps mirror the
# built-in "Red Pulses" timing (speed 150, delay 10) read from the device.
LEDS = {
  'working': ('solid', '0030C0'),
  'done': ('solid', '00C000'),
  'error': ('solid', 'FF0000'),
  'attention': ('pattern', [(127, 'FF6000', 150, 10), (127, '200C00', 150, 10)]),
}


def state_dir():
  path = Path(os.environ.get('BUSYTAG_STATE_DIR', Path.home() / '.cache' / 'busytag'))
  path.mkdir(parents=True, exist_ok=True)
  return path


@contextmanager
def locked_state():
  """Yield the state dict under an exclusive lock; it is saved on exit."""
  directory = state_dir()
  with open(directory / 'lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    path = directory / 'state.json'
    try:
      state = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
      state = {}
    state.setdefault('agents', {})
    yield state
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2))
    temp.replace(path)


def apply_update(state, agent, new_state, label=None, detail=None, timestamp=None, now=None):
  """Record one agent's report. Returns False if it was older than what we have."""
  now = time.time() if now is None else now
  timestamp = now if timestamp is None else timestamp
  agents = state['agents']

  for name in [name for name, entry in agents.items() if now - entry['updated'] > STALE_SECONDS]:
    del agents[name]

  current = agents.get(agent)
  # Hooks run in the background, so a late process must not undo a newer report
  if current and current['updated'] > timestamp:
    return False
  if new_state == 'clear':
    agents.pop(agent, None)
    return True
  if new_state not in PRIORITY:
    raise ValueError(f"unknown state '{new_state}'; use one of {', '.join(STATES)} or clear")
  agents[agent] = {
    'state': new_state,
    'label': label or (current or {}).get('label') or agent,
    'detail': detail or '',
    'updated': timestamp,
  }
  return True


def summarize(agents):
  """Return (top_state, rows) where rows are (label, state, detail), most urgent first."""
  active = [entry for entry in agents.values() if entry['state'] != 'idle']
  if not active:
    return 'idle', []
  active.sort(key=lambda entry: (-PRIORITY[entry['state']], -entry['updated']))
  rows = [(entry['label'], entry['state'], entry['detail']) for entry in active]
  return rows[0][1], rows


def screen_key(top, rows):
  return None if top == 'idle' else json.dumps([top, rows])


def needs_push(state, top, rows):
  if top == 'idle':
    return 'home' in state
  return screen_key(top, rows) != state.get('shown_key')


def push(device, state, top, rows):
  """Make the device show `top`/`rows`, recording what is shown in `state`."""
  from busytag.render import render_status

  if top == 'idle':
    home = state.pop('home', None)
    if home:
      device.stop_pattern()
      if home.get('pattern'):
        device.set_custom_pattern(home['pattern'])
      device.show_image(home['image'])
      device.solid_color(home['color'])
    state.pop('shown_key', None)
    return

  if 'home' not in state:
    # Remember what the user had on screen so we can put it back when all agents finish
    color = device.query('AT+SC?').split(',')[1]
    image = device.current_image()
    # A leftover status screen (e.g. state file deleted) is not the user's own image
    state['home'] = {
      'image': 'def.png' if image in STATUS_FILES else image,
      'color': color,
      # The device has one pattern slot, and the attention pulse overwrites it
      'pattern': device.custom_pattern(),
    }

  next_file = STATUS_FILES[1] if state.get('shown_file') == STATUS_FILES[0] else STATUS_FILES[0]
  device.upload(next_file, render_status(top, rows))
  device.show_image(next_file)

  kind, value = LEDS[top]
  if kind == 'solid':
    # AT+SC alone leaves AT+PP reporting the old pattern as playing
    device.stop_pattern()
    device.solid_color(value)
  else:
    device.set_custom_pattern(value)
    device.play_pattern(255)

  state['shown_file'] = next_file
  state['shown_key'] = screen_key(top, rows)


def refresh(state, open_device):
  """Push to the device if needed. Device problems are recorded, not raised, so the
  agent's report is still saved and the next update retries the screen."""
  from busytag.device import BusyTagError

  top, rows = summarize(state['agents'])
  if not needs_push(state, top, rows):
    return
  try:
    with open_device() as device:
      push(device, state, top, rows)
    state.pop('last_error', None)
  except (BusyTagError, OSError) as error:
    state.pop('shown_key', None)
    state['last_error'] = f'{time.strftime("%Y-%m-%d %H:%M:%S")} {error}'


def default_device():
  from busytag.device import Device
  return Device()


def update(agent, new_state, label=None, detail=None, timestamp=None, open_device=default_device):
  """Record a report and refresh the device if the screen should change."""
  with locked_state() as state:
    if apply_update(state, agent, new_state, label, detail, timestamp):
      refresh(state, open_device)
    return state.get('last_error')


def reset(open_device=default_device):
  """Forget every agent and put the user's own image and LEDs back."""
  with locked_state() as state:
    state['agents'] = {}
    refresh(state, open_device)
    return state.get('last_error')


def agents():
  """Return ([(agent, entry)] most urgent first, last device error)."""
  with locked_state() as state:
    entries = sorted(
      state['agents'].items(),
      key=lambda item: (-PRIORITY[item[1]['state']], -item[1]['updated']),
    )
    return entries, state.get('last_error')
